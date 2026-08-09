from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus, ModuleCode, TransferStatus
from app.models.domain import (
    Event,
    EventDocument,
    EventModuleTarget,
    Product,
    ProductionBatch,
    Purchase,
    Recipe,
    Supplier,
    Transfer,
    Unit,
)
from app.schemas.operator import (
    ModuleStateResult,
    OperatorMessageRequest,
    OperatorMessageResponse,
    ProductionResult,
    PurchaseResult,
    TransferResult,
)
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.events import create_event, set_event_module_status
from app.services.feed_mill import dispatch_transfer, produce, receive_transfer
from app.services.inventory import InsufficientStockError
from app.services.operator_agent import interpret_operator_message
from app.services.permissions import require_module_permission
from app.services.receipts import DuplicateInvoiceError, process_material_receipt


class InvalidUnitError(RuntimeError):
    pass


def _resolve_unit(session: Session, organization_id: str, code: str) -> Unit:
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == organization_id,
            Unit.code == code,
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise InvalidUnitError(f"Unidade '{code}' não encontrada para a organização.")
    return unit


def _module_states(session: Session, event_id: str) -> list[ModuleStateResult]:
    rows = list(session.scalars(select(EventModuleTarget).where(EventModuleTarget.event_id == event_id)))
    return [
        ModuleStateResult(
            module_code=row.module_code,
            status=row.status,
            requires_approval=row.requires_approval,
        )
        for row in rows
    ]


def _transfer_result(session: Session, transfer: Transfer) -> TransferResult:
    product = session.get(Product, transfer.product_id)
    source = session.get(Unit, transfer.source_unit_id)
    destination = session.get(Unit, transfer.destination_unit_id)
    return TransferResult(
        transfer_id=transfer.id,
        product_name=product.name if product else "",
        source_unit_code=source.code if source else "",
        destination_unit_code=destination.code if destination else "",
        dispatched_quantity=transfer.quantity,
        declared_quantity=transfer.declared_quantity,
        declared_unit=transfer.declared_unit,
        received_quantity=transfer.received_quantity,
        unit_cost=transfer.unit_cost,
        total_value=transfer.total_value,
        status=transfer.status,
    )


def _purchase_result(session: Session, purchase: Purchase) -> PurchaseResult:
    supplier = session.get(Supplier, purchase.supplier_id)
    return PurchaseResult(
        purchase_id=purchase.id,
        supplier_name=supplier.name if supplier else "",
        invoice_number=purchase.invoice_number,
        total_amount=purchase.total_amount,
        status=purchase.status,
    )


def _existing_event_response(session: Session, event: Event) -> OperatorMessageResponse:
    targets = list(session.scalars(select(EventModuleTarget.module_code).where(EventModuleTarget.event_id == event.id)))
    production = session.scalar(select(ProductionBatch).where(ProductionBatch.event_id == event.id))
    production_result = None
    if production is not None:
        recipe = session.get(Recipe, production.recipe_id)
        production_result = ProductionResult(
            production_batch_id=production.id,
            recipe_name=recipe.name if recipe else "",
            batch_count=production.batch_count,
            output_quantity=production.output_quantity,
            total_material_cost=production.total_material_cost,
            output_unit_cost=production.output_unit_cost,
        )

    transfer = session.scalar(
        select(Transfer).where(or_(Transfer.dispatch_event_id == event.id, Transfer.receipt_event_id == event.id))
    )
    purchase = session.scalar(select(Purchase).where(Purchase.event_id == event.id))
    return OperatorMessageResponse(
        event_id=event.id,
        status=event.status,
        event_type=event.event_type or "unclassified",
        target_modules=targets,
        module_states=_module_states(session, event.id),
        confidence=event.confidence,
        reason="duplicate_event",
        production=production_result,
        transfer=_transfer_result(session, transfer) if transfer else None,
        purchase=_purchase_result(session, purchase) if purchase else None,
    )


def _response(session: Session, event: Event, *, question=None, reason=None, production=None, transfer=None, purchase=None) -> OperatorMessageResponse:
    states = _module_states(session, event.id)
    return OperatorMessageResponse(
        event_id=event.id,
        status=event.status,
        event_type=event.event_type or "unclassified",
        target_modules=[row.module_code for row in states],
        module_states=states,
        confidence=event.confidence,
        question=question,
        reason=reason,
        production=production,
        transfer=transfer,
        purchase=purchase,
    )


def handle_operator_message(session: Session, *, principal: Principal, request: OperatorMessageRequest) -> OperatorMessageResponse:
    unit = _resolve_unit(session, principal.organization_id, request.unit_code)
    if request.external_id:
        existing = session.scalar(
            select(Event).where(
                Event.organization_id == principal.organization_id,
                Event.channel == request.channel,
                Event.correlation_id == request.external_id,
            )
        )
        if existing is not None:
            return _existing_event_response(session, existing)

    document_data = request.document.extracted_data if request.document else {}
    document_type = request.document.document_type if request.document else None
    interpretation = interpret_operator_message(
        session,
        principal.organization_id,
        unit.id,
        request.text,
        document_data=document_data,
        document_type=document_type,
    )

    for module_code in interpretation.permission_modules:
        require_module_permission(session, principal, module_code, "can_register")

    event = create_event(
        session,
        organization_id=principal.organization_id,
        unit_id=unit.id,
        actor_user_id=principal.user_id,
        channel=request.channel,
        source_type=request.source_type,
        source_original=request.text,
        target_modules=interpretation.target_modules,
        event_type=interpretation.event_type,
        interpretation={
            "intent": interpretation.intent,
            "data": interpretation.data,
            "missing_fields": interpretation.missing_fields,
        },
        confidence=interpretation.confidence,
        correlation_id=request.external_id,
        require_target=bool(interpretation.target_modules),
    )

    if request.document is not None:
        session.add(
            EventDocument(
                event_id=event.id,
                document_type=request.document.document_type,
                filename=request.document.filename,
                mime_type=request.document.mime_type,
                storage_ref=request.document.storage_ref,
                sha256=request.document.sha256,
                extracted_data=request.document.extracted_data,
            )
        )
        session.flush()

    if interpretation.missing_fields:
        event.status = EventStatus.WAITING_COMPLEMENT.value
        for module_code in interpretation.target_modules:
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=module_code,
                status=EventStatus.WAITING_COMPLEMENT.value,
            )
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="operator_event_waiting_complement",
            details={"missing_fields": interpretation.missing_fields},
        )
        session.flush()
        return _response(session, event, question=interpretation.question)

    event.status = EventStatus.INTERPRETED.value

    if interpretation.intent == "feed_mill_production":
        recipe = session.get(Recipe, interpretation.data["recipe_id"])
        try:
            with session.begin_nested():
                production = produce(
                    session,
                    organization_id=principal.organization_id,
                    unit_id=unit.id,
                    recipe_id=recipe.id,
                    batch_count=interpretation.data["batch_count"],
                    event_id=event.id,
                )
        except InsufficientStockError as exc:
            event.status = EventStatus.WAITING_MANAGER.value
            event.requires_approval = True
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=ModuleCode.FEED_MILL.value,
                status=EventStatus.WAITING_MANAGER.value,
                requires_approval=True,
            )
            record_audit(
                session,
                organization_id=principal.organization_id,
                event_id=event.id,
                actor_user_id=principal.user_id,
                action="operator_event_waiting_manager",
                details={"reason": str(exc), "kind": "insufficient_stock"},
            )
            return _response(session, event, reason=str(exc))

        event.status = EventStatus.PROCESSED.value
        set_event_module_status(
            session,
            event_id=event.id,
            module_code=ModuleCode.FEED_MILL.value,
            status=EventStatus.PROCESSED.value,
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="feed_mill_production_processed",
            details={
                "production_batch_id": production.id,
                "recipe_id": recipe.id,
                "batch_count": str(production.batch_count),
                "output_quantity": str(production.output_quantity),
                "total_material_cost": str(production.total_material_cost),
            },
        )
        return _response(
            session,
            event,
            production=ProductionResult(
                production_batch_id=production.id,
                recipe_name=recipe.name,
                batch_count=production.batch_count,
                output_quantity=production.output_quantity,
                total_material_cost=production.total_material_cost,
                output_unit_cost=production.output_unit_cost,
            ),
        )

    if interpretation.intent == "feed_mill_transfer_dispatch":
        try:
            with session.begin_nested():
                transfer = dispatch_transfer(
                    session,
                    organization_id=principal.organization_id,
                    source_unit_id=unit.id,
                    destination_unit_id=interpretation.data["destination_unit_id"],
                    product_id=interpretation.data["product_id"],
                    quantity=interpretation.data["base_quantity"],
                    event_id=event.id,
                    declared_quantity=interpretation.data.get("quantity_input"),
                    declared_unit=interpretation.data.get("quantity_unit"),
                )
        except InsufficientStockError as exc:
            event.status = EventStatus.WAITING_MANAGER.value
            event.requires_approval = True
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=ModuleCode.FEED_MILL.value,
                status=EventStatus.WAITING_MANAGER.value,
                requires_approval=True,
            )
            record_audit(
                session,
                organization_id=principal.organization_id,
                event_id=event.id,
                actor_user_id=principal.user_id,
                action="transfer_waiting_manager",
                details={"reason": str(exc), "kind": "insufficient_stock"},
            )
            return _response(session, event, reason=str(exc))

        event.status = EventStatus.PROCESSED.value
        set_event_module_status(
            session,
            event_id=event.id,
            module_code=ModuleCode.FEED_MILL.value,
            status=EventStatus.PROCESSED.value,
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="feed_mill_transfer_dispatched",
            details={"transfer_id": transfer.id, "total_value": str(transfer.total_value)},
        )
        return _response(session, event, transfer=_transfer_result(session, transfer))

    if interpretation.intent == "feed_mill_transfer_receipt":
        transfer = receive_transfer(
            session,
            organization_id=principal.organization_id,
            transfer_id=interpretation.data["transfer_id"],
            event_id=event.id,
            received_quantity=interpretation.data["received_quantity"],
        )
        if transfer.status == TransferStatus.DIVERGENT.value:
            event.status = EventStatus.WAITING_MANAGER.value
            event.requires_approval = True
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=ModuleCode.FEED_MILL.value,
                status=EventStatus.WAITING_MANAGER.value,
                requires_approval=True,
            )
            record_audit(
                session,
                organization_id=principal.organization_id,
                event_id=event.id,
                actor_user_id=principal.user_id,
                action="transfer_receipt_divergent",
                details={
                    "transfer_id": transfer.id,
                    "dispatched_quantity": str(transfer.quantity),
                    "received_quantity": str(transfer.received_quantity),
                    "divergence_quantity": str(transfer.divergence_quantity),
                },
            )
            return _response(
                session,
                event,
                reason="Quantidade recebida difere da quantidade enviada.",
                transfer=_transfer_result(session, transfer),
            )

        event.status = EventStatus.PROCESSED.value
        set_event_module_status(
            session,
            event_id=event.id,
            module_code=ModuleCode.FEED_MILL.value,
            status=EventStatus.PROCESSED.value,
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="feed_mill_transfer_received",
            details={"transfer_id": transfer.id, "received_quantity": str(transfer.received_quantity)},
        )
        return _response(session, event, transfer=_transfer_result(session, transfer))

    if interpretation.intent == "feed_mill_material_receipt":
        try:
            movement, purchase, _supplier = process_material_receipt(
                session,
                organization_id=principal.organization_id,
                unit_id=unit.id,
                event_id=event.id,
                data=interpretation.data,
            )
        except DuplicateInvoiceError as exc:
            event.status = EventStatus.WAITING_MANAGER.value
            event.requires_approval = True
            for module_code in interpretation.target_modules:
                set_event_module_status(
                    session,
                    event_id=event.id,
                    module_code=module_code,
                    status=EventStatus.WAITING_MANAGER.value,
                    requires_approval=True,
                )
            record_audit(
                session,
                organization_id=principal.organization_id,
                event_id=event.id,
                actor_user_id=principal.user_id,
                action="invoice_duplicate_blocked",
                details={"reason": str(exc)},
            )
            return _response(session, event, reason=str(exc))

        set_event_module_status(
            session,
            event_id=event.id,
            module_code=ModuleCode.FEED_MILL.value,
            status=EventStatus.PROCESSED.value,
        )
        waiting_manager = False
        if interpretation.data.get("has_nonconformity"):
            waiting_manager = True
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=ModuleCode.FEED_MILL.value,
                status=EventStatus.WAITING_MANAGER.value,
                requires_approval=True,
            )

        if purchase is not None:
            waiting_manager = True
            set_event_module_status(
                session,
                event_id=event.id,
                module_code=ModuleCode.FINANCE.value,
                status=EventStatus.WAITING_MANAGER.value,
                requires_approval=True,
            )

        if waiting_manager:
            event.status = EventStatus.WAITING_MANAGER.value
            event.requires_approval = True
        else:
            event.status = EventStatus.PROCESSED.value

        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="material_receipt_processed",
            details={
                "inventory_movement_id": movement.id,
                "purchase_id": purchase.id if purchase else None,
                "quantity": interpretation.data["quantity"],
                "unit_cost": interpretation.data["unit_cost"],
                "nonconformity": interpretation.data.get("has_nonconformity", False),
            },
        )
        return _response(
            session,
            event,
            reason="Compra aguardando aprovação gerencial." if purchase else None,
            purchase=_purchase_result(session, purchase) if purchase else None,
        )

    event.status = EventStatus.WAITING_COMPLEMENT.value
    return _response(session, event, question=interpretation.question)
