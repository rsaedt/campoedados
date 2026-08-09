from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus
from app.models.domain import Event, EventModuleTarget, ProductionBatch, Recipe, Unit
from app.schemas.operator import OperatorMessageRequest, OperatorMessageResponse, ProductionResult
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.events import create_event
from app.services.feed_mill import produce
from app.services.inventory import InsufficientStockError
from app.services.operator_agent import interpret_operator_message
from app.services.permissions import require_module_permission


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


def _existing_event_response(session: Session, event: Event) -> OperatorMessageResponse:
    targets = list(
        session.scalars(
            select(EventModuleTarget.module_code).where(EventModuleTarget.event_id == event.id)
        )
    )
    production = session.scalar(
        select(ProductionBatch).where(ProductionBatch.event_id == event.id)
    )
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
    return OperatorMessageResponse(
        event_id=event.id,
        status=event.status,
        event_type=event.event_type or "unclassified",
        target_modules=targets,
        confidence=event.confidence,
        reason="duplicate_event",
        production=production_result,
    )


def handle_operator_message(
    session: Session,
    *,
    principal: Principal,
    request: OperatorMessageRequest,
) -> OperatorMessageResponse:
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

    interpretation = interpret_operator_message(session, principal.organization_id, request.text)

    if interpretation.target_modules:
        for module_code in interpretation.target_modules:
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

    if interpretation.missing_fields:
        event.status = EventStatus.WAITING_COMPLEMENT.value
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="operator_event_waiting_complement",
            details={"missing_fields": interpretation.missing_fields},
        )
        session.flush()
        return OperatorMessageResponse(
            event_id=event.id,
            status=event.status,
            event_type=event.event_type or "unclassified",
            target_modules=interpretation.target_modules,
            confidence=event.confidence,
            question=interpretation.question,
        )

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
            record_audit(
                session,
                organization_id=principal.organization_id,
                event_id=event.id,
                actor_user_id=principal.user_id,
                action="operator_event_waiting_manager",
                details={"reason": str(exc), "kind": "insufficient_stock"},
            )
            session.flush()
            return OperatorMessageResponse(
                event_id=event.id,
                status=event.status,
                event_type=event.event_type or interpretation.event_type,
                target_modules=interpretation.target_modules,
                confidence=event.confidence,
                reason=str(exc),
            )

        event.status = EventStatus.PROCESSED.value
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
        session.flush()
        return OperatorMessageResponse(
            event_id=event.id,
            status=event.status,
            event_type=event.event_type or interpretation.event_type,
            target_modules=interpretation.target_modules,
            confidence=event.confidence,
            production=ProductionResult(
                production_batch_id=production.id,
                recipe_name=recipe.name,
                batch_count=production.batch_count,
                output_quantity=production.output_quantity,
                total_material_cost=production.total_material_cost,
                output_unit_cost=production.output_unit_cost,
            ),
        )

    event.status = EventStatus.WAITING_COMPLEMENT.value
    session.flush()
    return OperatorMessageResponse(
        event_id=event.id,
        status=event.status,
        event_type=event.event_type or "unclassified",
        target_modules=interpretation.target_modules,
        confidence=event.confidence,
        question=interpretation.question,
    )
