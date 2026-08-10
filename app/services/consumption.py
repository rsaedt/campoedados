from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import MovementType
from app.models.consumption import ConsumptionRecord
from app.services.inventory import get_balance, issue_stock, q_money, q_qty


def register_consumption(
    session: Session,
    *,
    organization_id: str,
    unit_id: str,
    product_id: str,
    quantity,
    event_id: str,
    purpose_code: str,
    purpose_label: str,
    context_label: str | None = None,
    notes: str | None = None,
) -> tuple[ConsumptionRecord, Decimal]:
    """Baixa o estoque da fazenda e registra para que o produto foi usado."""

    qty = q_qty(Decimal(str(quantity)))
    movement, unit_cost = issue_stock(
        session,
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=product_id,
        quantity=qty,
        movement_type=MovementType.CONSUMPTION.value,
        event_id=event_id,
        reference_type="consumption",
    )
    record = ConsumptionRecord(
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=product_id,
        event_id=event_id,
        inventory_movement_id=movement.id,
        quantity=qty,
        unit_cost=unit_cost,
        total_value=q_money(qty * unit_cost),
        purpose_code=purpose_code,
        purpose_label=purpose_label,
        context_label=context_label,
        notes=notes,
    )
    session.add(record)
    session.flush()
    movement.reference_id = record.id

    balance = get_balance(session, organization_id, unit_id, product_id, create=False)
    remaining = Decimal("0") if balance is None else Decimal(balance.quantity)
    session.flush()
    return record, remaining
