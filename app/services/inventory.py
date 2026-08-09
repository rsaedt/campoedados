from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import InventoryBalance, InventoryMovement


QTY = Decimal("0.0001")
COST = Decimal("0.000001")
MONEY = Decimal("0.01")


class InsufficientStockError(RuntimeError):
    pass


def d(value) -> Decimal:
    return Decimal(str(value))


def q_qty(value: Decimal) -> Decimal:
    return d(value).quantize(QTY, rounding=ROUND_HALF_UP)


def q_cost(value: Decimal) -> Decimal:
    return d(value).quantize(COST, rounding=ROUND_HALF_UP)


def q_money(value: Decimal) -> Decimal:
    return d(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def get_balance(session: Session, organization_id: str, unit_id: str, product_id: str, create: bool = True) -> InventoryBalance | None:
    balance = session.scalar(
        select(InventoryBalance).where(
            InventoryBalance.organization_id == organization_id,
            InventoryBalance.unit_id == unit_id,
            InventoryBalance.product_id == product_id,
        )
    )
    if balance is None and create:
        balance = InventoryBalance(
            organization_id=organization_id,
            unit_id=unit_id,
            product_id=product_id,
            quantity=Decimal("0"),
            avg_unit_cost=Decimal("0"),
        )
        session.add(balance)
        session.flush()
    return balance


def receive_stock(
    session: Session,
    *,
    organization_id: str,
    unit_id: str,
    product_id: str,
    quantity,
    unit_cost,
    movement_type: str,
    event_id: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> InventoryMovement:
    quantity = q_qty(d(quantity))
    unit_cost = q_cost(d(unit_cost))
    if quantity <= 0:
        raise ValueError("Quantidade de entrada deve ser maior que zero.")
    if unit_cost < 0:
        raise ValueError("Custo unitário não pode ser negativo.")

    balance = get_balance(session, organization_id, unit_id, product_id, create=True)
    previous_qty = d(balance.quantity)
    previous_value = previous_qty * d(balance.avg_unit_cost)
    incoming_value = quantity * unit_cost
    new_qty = previous_qty + quantity
    new_avg = Decimal("0") if new_qty == 0 else (previous_value + incoming_value) / new_qty

    balance.quantity = q_qty(new_qty)
    balance.avg_unit_cost = q_cost(new_avg)

    movement = InventoryMovement(
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=product_id,
        event_id=event_id,
        movement_type=movement_type,
        quantity=quantity,
        unit_cost=unit_cost,
        total_value=q_money(incoming_value),
        reference_type=reference_type,
        reference_id=reference_id,
    )
    session.add(movement)
    session.flush()
    return movement


def issue_stock(
    session: Session,
    *,
    organization_id: str,
    unit_id: str,
    product_id: str,
    quantity,
    movement_type: str,
    event_id: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> tuple[InventoryMovement, Decimal]:
    quantity = q_qty(d(quantity))
    if quantity <= 0:
        raise ValueError("Quantidade de saída deve ser maior que zero.")

    balance = get_balance(session, organization_id, unit_id, product_id, create=False)
    if balance is None or d(balance.quantity) < quantity:
        available = Decimal("0") if balance is None else d(balance.quantity)
        raise InsufficientStockError(f"Estoque insuficiente: disponível={available}, solicitado={quantity}.")

    unit_cost = q_cost(d(balance.avg_unit_cost))
    total_value = q_money(quantity * unit_cost)
    balance.quantity = q_qty(d(balance.quantity) - quantity)
    if d(balance.quantity) == 0:
        balance.avg_unit_cost = Decimal("0")

    movement = InventoryMovement(
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=product_id,
        event_id=event_id,
        movement_type=movement_type,
        quantity=-quantity,
        unit_cost=unit_cost,
        total_value=-total_value,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    session.add(movement)
    session.flush()
    return movement, unit_cost
