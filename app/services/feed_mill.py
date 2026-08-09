from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import ModuleCode, MovementType, TransferStatus
from app.models.domain import ProductionBatch, Recipe, Transfer
from app.services.inventory import d, get_balance, issue_stock, q_cost, q_money, q_qty, receive_stock
from app.services.modules import require_module


class InvalidTransferError(RuntimeError):
    pass


def produce(
    session: Session,
    *,
    organization_id: str,
    unit_id: str,
    recipe_id: str,
    batch_count,
    event_id: str | None = None,
) -> ProductionBatch:
    require_module(session, organization_id, ModuleCode.FEED_MILL.value)
    batches = q_qty(d(batch_count))
    if batches <= 0:
        raise ValueError("Número de batidas deve ser maior que zero.")

    recipe = session.get(Recipe, recipe_id)
    if recipe is None or recipe.organization_id != organization_id:
        raise ValueError("Fórmula não encontrada para a organização.")

    # Valida toda a fórmula antes de movimentar qualquer item, evitando baixa parcial.
    for ingredient in recipe.ingredients:
        qty = q_qty(d(ingredient.quantity_per_batch) * batches)
        balance = get_balance(session, organization_id, unit_id, ingredient.product_id, create=False)
        available = Decimal("0") if balance is None else d(balance.quantity)
        if available < qty:
            from app.services.inventory import InsufficientStockError
            raise InsufficientStockError(
                f"Estoque insuficiente para {ingredient.product.name}: disponível={available}, solicitado={qty}."
            )

    total_material_cost = Decimal("0")
    for ingredient in recipe.ingredients:
        qty = q_qty(d(ingredient.quantity_per_batch) * batches)
        movement, unit_cost = issue_stock(
            session,
            organization_id=organization_id,
            unit_id=unit_id,
            product_id=ingredient.product_id,
            quantity=qty,
            movement_type=MovementType.PRODUCTION_CONSUMPTION.value,
            event_id=event_id,
            reference_type="recipe",
            reference_id=recipe.id,
        )
        cost = q_money(qty * unit_cost)
        total_material_cost += cost

    output_qty = q_qty(d(recipe.output_quantity_per_batch) * batches)
    total_material_cost = q_money(total_material_cost)
    output_unit_cost = q_cost(total_material_cost / output_qty)

    production = ProductionBatch(
        organization_id=organization_id,
        unit_id=unit_id,
        recipe_id=recipe.id,
        event_id=event_id,
        batch_count=batches,
        output_quantity=output_qty,
        total_material_cost=total_material_cost,
        output_unit_cost=output_unit_cost,
    )
    session.add(production)
    session.flush()

    receive_stock(
        session,
        organization_id=organization_id,
        unit_id=unit_id,
        product_id=recipe.output_product_id,
        quantity=output_qty,
        unit_cost=output_unit_cost,
        movement_type=MovementType.PRODUCTION_OUTPUT.value,
        event_id=event_id,
        reference_type="production_batch",
        reference_id=production.id,
    )
    session.flush()
    return production


def dispatch_transfer(
    session: Session,
    *,
    organization_id: str,
    source_unit_id: str,
    destination_unit_id: str,
    product_id: str,
    quantity,
    event_id: str | None = None,
    declared_quantity=None,
    declared_unit: str | None = None,
) -> Transfer:
    require_module(session, organization_id, ModuleCode.FEED_MILL.value)
    if source_unit_id == destination_unit_id:
        raise InvalidTransferError("Origem e destino não podem ser iguais.")

    qty = q_qty(d(quantity))
    _, unit_cost = issue_stock(
        session,
        organization_id=organization_id,
        unit_id=source_unit_id,
        product_id=product_id,
        quantity=qty,
        movement_type=MovementType.TRANSFER_DISPATCH.value,
        event_id=event_id,
        reference_type="transfer_dispatch",
    )
    total_value = q_money(qty * unit_cost)
    transfer = Transfer(
        organization_id=organization_id,
        source_unit_id=source_unit_id,
        destination_unit_id=destination_unit_id,
        product_id=product_id,
        dispatch_event_id=event_id,
        quantity=qty,
        declared_quantity=q_qty(d(declared_quantity)) if declared_quantity is not None else None,
        declared_unit=declared_unit,
        unit_cost=unit_cost,
        total_value=total_value,
        status=TransferStatus.IN_TRANSIT.value,
    )
    session.add(transfer)
    session.flush()
    return transfer


def receive_transfer(
    session: Session,
    *,
    organization_id: str,
    transfer_id: str,
    event_id: str | None = None,
    received_quantity=None,
    approve_divergence: bool = False,
) -> Transfer:
    require_module(session, organization_id, ModuleCode.FEED_MILL.value)
    transfer = session.get(Transfer, transfer_id)
    if transfer is None or transfer.organization_id != organization_id:
        raise InvalidTransferError("Transferência não encontrada.")
    if transfer.status not in {TransferStatus.IN_TRANSIT.value, TransferStatus.DIVERGENT.value}:
        raise InvalidTransferError("Somente transferências em trânsito/divergentes podem ser recebidas.")

    actual_qty = q_qty(d(received_quantity if received_quantity is not None else transfer.quantity))
    dispatched_qty = q_qty(d(transfer.quantity))
    divergence = q_qty(actual_qty - dispatched_qty)
    transfer.receipt_event_id = event_id or transfer.receipt_event_id
    transfer.received_quantity = actual_qty
    transfer.divergence_quantity = divergence

    if divergence != 0 and not approve_divergence:
        transfer.status = TransferStatus.DIVERGENT.value
        session.flush()
        return transfer

    receive_stock(
        session,
        organization_id=organization_id,
        unit_id=transfer.destination_unit_id,
        product_id=transfer.product_id,
        quantity=actual_qty,
        unit_cost=transfer.unit_cost,
        movement_type=MovementType.TRANSFER_RECEIPT.value,
        event_id=event_id,
        reference_type="transfer",
        reference_id=transfer.id,
    )
    transfer.status = TransferStatus.RECEIVED.value
    transfer.received_at = datetime.now(timezone.utc)
    session.flush()
    return transfer
