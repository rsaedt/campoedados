from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus, ModuleCode, MovementType
from app.models.domain import Event, EventDocument, EventModuleTarget, Unit
from app.schemas.operator import ModuleStateResult, OperatorDocumentInput, OperatorMessageRequest, OperatorMessageResponse
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.events import create_event, set_event_module_status
from app.services.inventory import receive_stock
from app.services.modules import module_enabled
from app.services.operator import _existing_event_response, handle_operator_message
from app.services.operator_agent import interpret_operator_message
from app.services.permissions import require_module_permission


FINANCE_ONLY_MISSING = {"supplier_name", "invoice_number", "installments", "installment_total"}


class InvalidInvoiceMediaError(ValueError):
    pass


class DuplicateDocumentError(RuntimeError):
    pass


def flatten_invoice_extraction(extraction: dict) -> dict:
    if extraction.get("document_kind") != "invoice":
        raise InvalidInvoiceMediaError("O arquivo não foi reconhecido como nota fiscal/documento de compra.")

    items = extraction.get("items") or []
    first = items[0] if len(items) == 1 else {}
    total = extraction.get("invoice_total")
    if total is None:
        total = first.get("total_amount")

    installments = [
        row for row in (extraction.get("installments") or [])
        if row.get("due_date") is not None and row.get("amount") is not None
    ]
    return {
        "supplier_name": extraction.get("supplier_name"),
        "supplier_document": extraction.get("supplier_document"),
        "invoice_number": extraction.get("invoice_number"),
        "issue_date": extraction.get("issue_date"),
        "product_name": first.get("product_name"),
        "quantity": first.get("quantity"),
        "unit": first.get("unit") or "kg",
        "unit_cost": first.get("unit_cost"),
        "total_amount": total,
        "installments": installments,
        "extraction_confidence": extraction.get("confidence"),
        "multiple_items": len(items) > 1,
        "raw_items": items,
    }


def _resolve_unit(session: Session, organization_id: str, unit_code: str) -> Unit:
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == organization_id,
            Unit.code == unit_code,
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise ValueError(f"Unidade '{unit_code}' não encontrada para a organização.")
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


def _duplicate_by_sha(session: Session, organization_id: str, sha256: str) -> Event | None:
    return session.scalar(
        select(Event)
        .join(EventDocument, EventDocument.event_id == Event.id)
        .where(Event.organization_id == organization_id, EventDocument.sha256 == sha256)
        .order_by(Event.received_at.asc())
    )


def _duplicate_by_invoice(session: Session, organization_id: str, data: dict) -> Event | None:
    invoice_number = data.get("invoice_number")
    supplier_document = data.get("supplier_document")
    supplier_name = data.get("supplier_name")
    if not invoice_number:
        return None
    rows = session.execute(
        select(Event, EventDocument)
        .join(EventDocument, EventDocument.event_id == Event.id)
        .where(Event.organization_id == organization_id, EventDocument.document_type == "invoice")
    ).all()
    for event, document in rows:
        extracted = document.extracted_data or {}
        same_invoice = str(extracted.get("invoice_number") or "") == str(invoice_number)
        same_supplier = False
        if supplier_document and extracted.get("supplier_document"):
            same_supplier = str(extracted.get("supplier_document")) == str(supplier_document)
        elif supplier_name and extracted.get("supplier_name"):
            same_supplier = str(extracted.get("supplier_name")).casefold() == str(supplier_name).casefold()
        if same_invoice and same_supplier:
            return event
    return None


def process_invoice_media(
    session: Session,
    *,
    principal: Principal,
    text: str,
    unit_code: str,
    channel: str,
    external_id: str | None,
    filename: str | None,
    mime_type: str,
    storage_ref: str,
    sha256: str,
    extraction: dict,
    received_quantity: str | None = None,
    received_unit: str | None = None,
) -> OperatorMessageResponse:
    duplicate = _duplicate_by_sha(session, principal.organization_id, sha256)
    if duplicate is not None:
        return _existing_event_response(session, duplicate)

    data = flatten_invoice_extraction(extraction)
    if received_quantity is not None:
        data["received_quantity"] = received_quantity
    if received_unit is not None:
        data["unit"] = received_unit

    duplicate_invoice = _duplicate_by_invoice(session, principal.organization_id, data)
    if duplicate_invoice is not None:
        return _existing_event_response(session, duplicate_invoice)

    document = OperatorDocumentInput(
        document_type="invoice",
        filename=filename,
        mime_type=mime_type,
        storage_ref=storage_ref,
        sha256=sha256,
        extracted_data=data,
    )
    request = OperatorMessageRequest(
        text=text or "Chegou material, segue nota fiscal.",
        unit_code=unit_code,
        channel=channel,
        source_type="image" if mime_type.startswith("image/") else "document",
        external_id=external_id,
        document=document,
    )

    unit = _resolve_unit(session, principal.organization_id, unit_code)
    interpretation = interpret_operator_message(
        session,
        principal.organization_id,
        unit.id,
        request.text,
        document_data=data,
        document_type="invoice",
    )
    finance_enabled = module_enabled(session, principal.organization_id, ModuleCode.FINANCE.value)
    missing = set(interpretation.missing_fields)
    finance_missing = missing & FINANCE_ONLY_MISSING
    physical_missing = missing - FINANCE_ONLY_MISSING

    if physical_missing or not finance_enabled or not finance_missing:
        return handle_operator_message(session, principal=principal, request=request)

    # A NF real pode não conter condição de pagamento. Nesse caso o estoque físico não espera o financeiro.
    require_module_permission(session, principal, ModuleCode.FEED_MILL.value, "can_register")
    event = create_event(
        session,
        organization_id=principal.organization_id,
        unit_id=unit.id,
        actor_user_id=principal.user_id,
        channel=channel,
        source_type=request.source_type,
        source_original=request.text,
        target_modules=interpretation.target_modules,
        event_type=interpretation.event_type,
        interpretation={
            "intent": interpretation.intent,
            "data": interpretation.data,
            "missing_fields": interpretation.missing_fields,
            "finance_missing_fields": sorted(finance_missing),
        },
        confidence=interpretation.confidence,
        correlation_id=external_id,
        require_target=True,
    )
    session.add(
        EventDocument(
            event_id=event.id,
            document_type="invoice",
            filename=filename,
            mime_type=mime_type,
            storage_ref=storage_ref,
            sha256=sha256,
            extracted_data=data,
        )
    )
    movement = receive_stock(
        session,
        organization_id=principal.organization_id,
        unit_id=unit.id,
        product_id=interpretation.data["product_id"],
        quantity=interpretation.data["quantity"],
        unit_cost=interpretation.data["unit_cost"],
        movement_type=MovementType.RECEIPT.value,
        event_id=event.id,
        reference_type="material_receipt",
        reference_id=event.id,
    )
    set_event_module_status(
        session,
        event_id=event.id,
        module_code=ModuleCode.FEED_MILL.value,
        status=EventStatus.PROCESSED.value,
    )
    set_event_module_status(
        session,
        event_id=event.id,
        module_code=ModuleCode.FINANCE.value,
        status=EventStatus.WAITING_COMPLEMENT.value,
    )
    event.status = EventStatus.WAITING_COMPLEMENT.value
    record_audit(
        session,
        organization_id=principal.organization_id,
        event_id=event.id,
        actor_user_id=principal.user_id,
        action="invoice_physical_receipt_finance_incomplete",
        details={
            "inventory_movement_id": movement.id,
            "finance_missing_fields": sorted(finance_missing),
            "document_sha256": sha256,
        },
    )
    session.flush()
    return OperatorMessageResponse(
        event_id=event.id,
        status=event.status,
        event_type=event.event_type or "feed_mill.material_receipt",
        target_modules=[row.module_code for row in _module_states(session, event.id)],
        module_states=_module_states(session, event.id),
        confidence=event.confidence,
        question=interpretation.question,
        reason="Entrada física registrada; dados financeiros ainda precisam ser complementados.",
    )


def process_audio_media(
    session: Session,
    *,
    principal: Principal,
    transcript: str,
    unit_code: str,
    channel: str,
    external_id: str | None,
    filename: str | None,
    mime_type: str,
    storage_ref: str,
    sha256: str,
) -> OperatorMessageResponse:
    duplicate = _duplicate_by_sha(session, principal.organization_id, sha256)
    if duplicate is not None:
        return _existing_event_response(session, duplicate)
    return handle_operator_message(
        session,
        principal=principal,
        request=OperatorMessageRequest(
            text=transcript,
            unit_code=unit_code,
            channel=channel,
            source_type="audio",
            external_id=external_id,
            document=OperatorDocumentInput(
                document_type="audio",
                filename=filename,
                mime_type=mime_type,
                storage_ref=storage_ref,
                sha256=sha256,
                extracted_data={"transcript": transcript},
            ),
        ),
    )
