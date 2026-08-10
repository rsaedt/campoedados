from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus, ModuleCode
from app.models.consumption import ConsumptionRecord
from app.models.domain import Event, EventModuleTarget, Product, Unit
from app.schemas.operator import (
    ConsumptionResult,
    ModuleStateResult,
    OperatorMessageRequest,
    OperatorMessageResponse,
)
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.consumption import register_consumption
from app.services.events import create_event, set_event_module_status
from app.services.inventory import InsufficientStockError
from app.services.modules import module_enabled
from app.services.operator import InvalidUnitError, handle_operator_message
from app.services.operator_agent import (
    OperatorInterpretation,
    _parse_quantity,
    _resolve_product,
    _to_base_quantity,
    normalize_text,
)
from app.services.permissions import require_module_permission


CONSUMPTION_MARKERS = (
    "tratei",
    "tratamos",
    "dei",
    "demos",
    "usei",
    "usamos",
    "consumi",
    "consumimos",
    "gastei",
    "gastamos",
    "coloquei",
    "colocamos",
    "joguei",
    "jogamos",
    "forneci",
    "fornecemos",
    "alimentei",
    "alimentamos",
)

LIVESTOCK_MARKERS = (
    "cavalo",
    "cavalos",
    "gado",
    "boi",
    "bois",
    "vaca",
    "vacas",
    "bezerro",
    "bezerros",
    "animal",
    "animais",
    "pasto",
    "cocho",
    "lote",
)

AGRICULTURE_MARKERS = (
    "lavoura",
    "plantio",
    "plantacao",
    "talhao",
    "roca",
    "agricultura",
)

FEED_MILL_MARKERS = (
    "fabrica",
    "misturador",
    "moagem",
    "moinho",
    "racao",
)


def _is_consumption(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in CONSUMPTION_MARKERS)


def _purpose(text: str) -> tuple[str, str, str | None]:
    normalized = normalize_text(text)
    context = None

    pasture = re.search(r"\bpasto\s*(?:n[ºo]?\s*)?(\d+[a-z]?)\b", normalized)
    paddock = re.search(r"\btalhao\s*(?:n[ºo]?\s*)?(\d+[a-z]?)\b", normalized)
    if pasture:
        context = f"Pasto {pasture.group(1)}"
    elif paddock:
        context = f"Talhão {paddock.group(1)}"
    elif "cavalos" in normalized or "cavalo" in normalized:
        context = "Cavalos"
    elif "gado" in normalized:
        context = "Gado"

    if any(marker in normalized for marker in LIVESTOCK_MARKERS):
        return "livestock", "Pecuária", context
    if any(marker in normalized for marker in AGRICULTURE_MARKERS):
        return "agriculture", "Agricultura", context
    if any(marker in normalized for marker in FEED_MILL_MARKERS):
        return "feed_mill", "Fábrica de Ração", context
    return "farm_use", "Uso da fazenda", context


def _target_modules(session: Session, organization_id: str, purpose_code: str) -> list[str]:
    preferred = None
    if purpose_code == "livestock":
        preferred = ModuleCode.LIVESTOCK.value
    elif purpose_code == "feed_mill":
        preferred = ModuleCode.FEED_MILL.value

    if preferred and module_enabled(session, organization_id, preferred):
        return [preferred]

    # Estoque é compartilhado pela fazenda. Quando a finalidade não corresponde
    # a um módulo comercial específico, vinculamos o evento a um módulo operacional
    # habilitado apenas para visibilidade/permissão, sem dizer que o produto "pertence" a ele.
    for fallback in (ModuleCode.FEED_MILL.value, ModuleCode.LIVESTOCK.value):
        if module_enabled(session, organization_id, fallback):
            return [fallback]
    return []


def interpret_natural_consumption(
    session: Session,
    organization_id: str,
    text: str,
) -> OperatorInterpretation | None:
    if not _is_consumption(text):
        return None

    product = _resolve_product(session, organization_id, text)
    qty, qty_unit = _parse_quantity(text)
    base_qty, conversion_error = _to_base_quantity(product, qty, qty_unit)
    purpose_code, purpose_label, context_label = _purpose(text)
    targets = _target_modules(session, organization_id, purpose_code)

    missing: list[str] = []
    if product is None:
        missing.append("product")
    if qty is None:
        missing.append("quantity")
    if conversion_error:
        missing.append(conversion_error)

    if len(missing) == 1:
        if missing[0] == "product":
            question = "Qual produto foi usado?"
        elif missing[0] == "quantity":
            question = "Quanto desse produto foi usado?"
        elif missing[0] == "package_weight":
            product_name = product.name if product else "desse produto"
            question = f"Quantos quilos tem cada saco de {product_name}?"
        else:
            question = "Qual quantidade foi usada?"
    elif missing:
        question = "Preciso saber qual produto foi usado e a quantidade."
    else:
        question = None

    return OperatorInterpretation(
        intent="inventory_consumption",
        event_type="inventory.consumption",
        target_modules=targets,
        permission_modules=targets,
        confidence=Decimal("0.9800") if not missing else Decimal("0.6800"),
        data={
            "product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "quantity_input": str(qty) if qty is not None else None,
            "quantity_unit": qty_unit,
            "base_quantity": str(base_qty) if base_qty is not None else None,
            "purpose_code": purpose_code,
            "purpose_label": purpose_label,
            "context_label": context_label,
        },
        missing_fields=missing,
        question=question,
    )


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


def _consumption_result(
    session: Session,
    record: ConsumptionRecord,
    remaining_quantity: Decimal,
) -> ConsumptionResult:
    product = session.get(Product, record.product_id)
    unit = session.get(Unit, record.unit_id)
    return ConsumptionResult(
        consumption_id=record.id,
        product_name=product.name if product else record.product_id,
        unit_code=unit.code if unit else record.unit_id,
        quantity=record.quantity,
        base_unit=product.base_unit if product else "",
        unit_cost=record.unit_cost,
        total_value=record.total_value,
        purpose_code=record.purpose_code,
        purpose_label=record.purpose_label,
        context_label=record.context_label,
        remaining_quantity=remaining_quantity,
    )


def _response(
    session: Session,
    event: Event,
    *,
    question: str | None = None,
    reason: str | None = None,
    consumption: ConsumptionResult | None = None,
) -> OperatorMessageResponse:
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
        consumption=consumption,
    )


def handle_operator_message_natural(
    session: Session,
    *,
    principal: Principal,
    request: OperatorMessageRequest,
) -> OperatorMessageResponse:
    interpretation = interpret_natural_consumption(
        session,
        principal.organization_id,
        request.text,
    )
    if interpretation is None:
        return handle_operator_message(session, principal=principal, request=request)

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
            record = session.scalar(
                select(ConsumptionRecord).where(ConsumptionRecord.event_id == existing.id)
            )
            if record is not None:
                from app.services.inventory import get_balance

                balance = get_balance(
                    session,
                    principal.organization_id,
                    record.unit_id,
                    record.product_id,
                    create=False,
                )
                remaining = Decimal("0") if balance is None else Decimal(balance.quantity)
                return _response(
                    session,
                    existing,
                    reason="duplicate_event",
                    consumption=_consumption_result(session, record, remaining),
                )
            return handle_operator_message(session, principal=principal, request=request)

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
            action="inventory_consumption_waiting_complement",
            details={"missing_fields": interpretation.missing_fields},
        )
        return _response(session, event, question=interpretation.question)

    try:
        with session.begin_nested():
            record, remaining = register_consumption(
                session,
                organization_id=principal.organization_id,
                unit_id=unit.id,
                product_id=interpretation.data["product_id"],
                quantity=interpretation.data["base_quantity"],
                event_id=event.id,
                purpose_code=interpretation.data["purpose_code"],
                purpose_label=interpretation.data["purpose_label"],
                context_label=interpretation.data.get("context_label"),
                notes=request.text,
            )
    except InsufficientStockError as exc:
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
            action="inventory_consumption_waiting_manager",
            details={"reason": str(exc), "kind": "insufficient_stock"},
        )
        return _response(session, event, reason=str(exc))

    event.status = EventStatus.PROCESSED.value
    for module_code in interpretation.target_modules:
        set_event_module_status(
            session,
            event_id=event.id,
            module_code=module_code,
            status=EventStatus.PROCESSED.value,
        )
    result = _consumption_result(session, record, remaining)
    record_audit(
        session,
        organization_id=principal.organization_id,
        event_id=event.id,
        actor_user_id=principal.user_id,
        action="inventory_consumption_processed",
        details={
            "consumption_id": record.id,
            "product_id": record.product_id,
            "quantity": str(record.quantity),
            "purpose_code": record.purpose_code,
            "purpose_label": record.purpose_label,
            "context_label": record.context_label,
            "total_value": str(record.total_value),
            "remaining_quantity": str(remaining),
        },
    )
    return _response(session, event, consumption=result)
