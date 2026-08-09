from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.core.enums import ModuleCode, MovementType, ProductType, TransferStatus
from app.models.domain import (
    InventoryBalance,
    InventoryMovement,
    Product,
    ProductionBatch,
    Recipe,
    Transfer,
    Unit,
)
from app.services.auth import Principal
from app.services.permissions import PermissionDeniedError, require_module_permission


router = APIRouter(prefix="/v1/dashboard/feed-mill", tags=["dashboard-feed-mill"])


def _num(value) -> float:
    return float(value or 0)


@router.get("")
def feed_mill_workspace(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        require_module_permission(session, principal, ModuleCode.FEED_MILL.value, "can_view")
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="Módulo Fábrica de Ração não disponível para este usuário.") from exc

    organization_id = principal.organization_id
    units = list(
        session.scalars(
            select(Unit)
            .where(Unit.organization_id == organization_id, Unit.active.is_(True))
            .order_by(Unit.code)
        )
    )
    products = list(
        session.scalars(
            select(Product)
            .where(Product.organization_id == organization_id, Product.active.is_(True))
            .order_by(Product.name)
        )
    )
    balances = list(
        session.scalars(
            select(InventoryBalance).where(InventoryBalance.organization_id == organization_id)
        )
    )
    recipes = list(
        session.scalars(
            select(Recipe)
            .where(Recipe.organization_id == organization_id)
            .order_by(Recipe.name)
        )
    )
    productions = list(
        session.scalars(
            select(ProductionBatch)
            .where(ProductionBatch.organization_id == organization_id)
            .order_by(ProductionBatch.created_at.desc())
            .limit(50)
        )
    )
    transfers = list(
        session.scalars(
            select(Transfer)
            .where(Transfer.organization_id == organization_id)
            .order_by(Transfer.dispatched_at.desc())
            .limit(50)
        )
    )
    entry_types = {
        MovementType.RECEIPT.value,
        MovementType.ADJUSTMENT.value,
        MovementType.TRANSFER_RECEIPT.value,
    }
    entries = list(
        session.scalars(
            select(InventoryMovement)
            .where(
                InventoryMovement.organization_id == organization_id,
                InventoryMovement.movement_type.in_(entry_types),
            )
            .order_by(InventoryMovement.created_at.desc())
            .limit(50)
        )
    )

    unit_by_id = {row.id: row for row in units}
    product_by_id = {row.id: row for row in products}
    recipe_by_id = {row.id: row for row in recipes}

    inventory_value = sum((Decimal(row.total_value) for row in balances), Decimal("0"))
    raw_material_value = sum(
        (
            Decimal(row.total_value)
            for row in balances
            if product_by_id.get(row.product_id)
            and product_by_id[row.product_id].product_type == ProductType.RAW_MATERIAL.value
        ),
        Decimal("0"),
    )
    finished_good_value = inventory_value - raw_material_value
    in_transit = [row for row in transfers if row.status == TransferStatus.IN_TRANSIT.value]

    raw_products = [row for row in products if row.product_type == ProductType.RAW_MATERIAL.value]
    total_raw_by_product = {
        product.id: sum(
            (Decimal(balance.quantity) for balance in balances if balance.product_id == product.id),
            Decimal("0"),
        )
        for product in raw_products
    }
    zero_raw_materials = [
        product.name for product in raw_products if total_raw_by_product.get(product.id, Decimal("0")) <= 0
    ]

    return {
        "summary": {
            "inventory_value": _num(inventory_value),
            "raw_material_value": _num(raw_material_value),
            "finished_good_value": _num(finished_good_value),
            "active_recipes": sum(1 for row in recipes if row.active),
            "production_count": len(productions),
            "transfers_in_transit": len(in_transit),
            "zero_raw_material_count": len(zero_raw_materials),
            "zero_raw_materials": zero_raw_materials,
        },
        "inventory": [
            {
                "unit_code": unit_by_id[row.unit_id].code if row.unit_id in unit_by_id else row.unit_id,
                "unit_name": unit_by_id[row.unit_id].name if row.unit_id in unit_by_id else "",
                "product_id": row.product_id,
                "product_name": product_by_id[row.product_id].name if row.product_id in product_by_id else row.product_id,
                "product_type": product_by_id[row.product_id].product_type if row.product_id in product_by_id else None,
                "base_unit": product_by_id[row.product_id].base_unit if row.product_id in product_by_id else "",
                "quantity": _num(row.quantity),
                "avg_unit_cost": _num(row.avg_unit_cost),
                "total_value": _num(row.total_value),
            }
            for row in balances
        ],
        "recipes": [
            {
                "id": recipe.id,
                "name": recipe.name,
                "active": recipe.active,
                "output_product_id": recipe.output_product_id,
                "output_product_name": product_by_id[recipe.output_product_id].name
                if recipe.output_product_id in product_by_id
                else recipe.output_product_id,
                "output_quantity_per_batch": _num(recipe.output_quantity_per_batch),
                "output_unit": product_by_id[recipe.output_product_id].base_unit
                if recipe.output_product_id in product_by_id
                else "",
                "ingredients": [
                    {
                        "product_id": ingredient.product_id,
                        "product_name": ingredient.product.name,
                        "quantity_per_batch": _num(ingredient.quantity_per_batch),
                        "base_unit": ingredient.product.base_unit,
                    }
                    for ingredient in recipe.ingredients
                ],
            }
            for recipe in recipes
        ],
        "productions": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "unit_code": unit_by_id[row.unit_id].code if row.unit_id in unit_by_id else row.unit_id,
                "recipe_name": recipe_by_id[row.recipe_id].name if row.recipe_id in recipe_by_id else row.recipe_id,
                "batch_count": _num(row.batch_count),
                "output_quantity": _num(row.output_quantity),
                "output_unit": (
                    product_by_id[recipe_by_id[row.recipe_id].output_product_id].base_unit
                    if row.recipe_id in recipe_by_id
                    and recipe_by_id[row.recipe_id].output_product_id in product_by_id
                    else ""
                ),
                "total_material_cost": _num(row.total_material_cost),
                "output_unit_cost": _num(row.output_unit_cost),
            }
            for row in productions
        ],
        "transfers": [
            {
                "id": row.id,
                "dispatched_at": row.dispatched_at.isoformat(),
                "received_at": row.received_at.isoformat() if row.received_at else None,
                "source_unit_code": unit_by_id[row.source_unit_id].code if row.source_unit_id in unit_by_id else row.source_unit_id,
                "destination_unit_code": unit_by_id[row.destination_unit_id].code if row.destination_unit_id in unit_by_id else row.destination_unit_id,
                "product_name": product_by_id[row.product_id].name if row.product_id in product_by_id else row.product_id,
                "base_unit": product_by_id[row.product_id].base_unit if row.product_id in product_by_id else "",
                "quantity": _num(row.quantity),
                "declared_quantity": _num(row.declared_quantity) if row.declared_quantity is not None else None,
                "declared_unit": row.declared_unit,
                "received_quantity": _num(row.received_quantity) if row.received_quantity is not None else None,
                "divergence_quantity": _num(row.divergence_quantity) if row.divergence_quantity is not None else None,
                "unit_cost": _num(row.unit_cost),
                "total_value": _num(row.total_value),
                "status": row.status,
            }
            for row in transfers
        ],
        "entries": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "unit_code": unit_by_id[row.unit_id].code if row.unit_id in unit_by_id else row.unit_id,
                "product_name": product_by_id[row.product_id].name if row.product_id in product_by_id else row.product_id,
                "base_unit": product_by_id[row.product_id].base_unit if row.product_id in product_by_id else "",
                "movement_type": row.movement_type,
                "quantity": _num(row.quantity),
                "unit_cost": _num(row.unit_cost),
                "total_value": _num(row.total_value),
                "reference_type": row.reference_type,
            }
            for row in entries
        ],
    }
