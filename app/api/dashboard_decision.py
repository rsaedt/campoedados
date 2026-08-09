from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, ProductType
from app.models.domain import (
    AuditEntry,
    Event,
    EventModuleTarget,
    InventoryBalance,
    Product,
    ProductionBatch,
    Unit,
)
from app.services.auth import Principal
from app.services.module_access import accessible_module_codes


router = APIRouter(prefix="/v1/dashboard", tags=["dashboard-decision"])


def _num(value) -> float:
    return float(value or 0)


def _event_reason(session: Session, event_id: str) -> str | None:
    audit = session.scalar(
        select(AuditEntry)
        .where(
            AuditEntry.event_id == event_id,
            AuditEntry.action == "operator_event_waiting_manager",
        )
        .order_by(AuditEntry.created_at.desc())
        .limit(1)
    )
    if audit is None or not isinstance(audit.details, dict):
        return None
    reason = audit.details.get("reason")
    return str(reason) if reason else None


@router.get("/decision-overview")
def decision_overview(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    organization_id = principal.organization_id
    visible_codes = accessible_module_codes(session, principal)
    feed_mill_visible = ModuleCode.FEED_MILL.value in visible_codes

    units = list(
        session.scalars(
            select(Unit)
            .where(Unit.organization_id == organization_id, Unit.active.is_(True))
            .order_by(Unit.code)
        )
    )

    products = (
        list(
            session.scalars(
                select(Product)
                .where(Product.organization_id == organization_id, Product.active.is_(True))
                .order_by(Product.name)
            )
        )
        if feed_mill_visible
        else []
    )
    balances = (
        list(
            session.scalars(
                select(InventoryBalance).where(InventoryBalance.organization_id == organization_id)
            )
        )
        if feed_mill_visible
        else []
    )

    if visible_codes:
        visible_event_ids = select(EventModuleTarget.event_id).where(
            EventModuleTarget.module_code.in_(visible_codes)
        )
        events = list(
            session.scalars(
                select(Event)
                .where(
                    Event.organization_id == organization_id,
                    Event.id.in_(visible_event_ids),
                )
                .order_by(Event.received_at.desc())
            )
        )
    else:
        events = []

    productions = (
        list(
            session.scalars(
                select(ProductionBatch)
                .where(ProductionBatch.organization_id == organization_id)
                .order_by(ProductionBatch.created_at.desc())
            )
        )
        if feed_mill_visible
        else []
    )

    product_by_id = {row.id: row for row in products}
    raw_products = [row for row in products if row.product_type == ProductType.RAW_MATERIAL.value]
    balance_by_unit_product = {(row.unit_id, row.product_id): row for row in balances}

    inventory_value = sum((Decimal(row.total_value) for row in balances), Decimal("0"))
    waiting_complement = [row for row in events if row.status == EventStatus.WAITING_COMPLEMENT.value]
    waiting_manager = [row for row in events if row.status == EventStatus.WAITING_MANAGER.value]

    unit_summaries = []
    for unit in units:
        unit_balances = [row for row in balances if row.unit_id == unit.id]
        positive_balances = [row for row in unit_balances if Decimal(row.quantity) > 0]
        unit_events = [row for row in events if row.unit_id == unit.id]
        unit_productions = [row for row in productions if row.unit_id == unit.id]
        zero_raw_materials = [
            product.name
            for product in raw_products
            if (
                (balance := balance_by_unit_product.get((unit.id, product.id))) is None
                or Decimal(balance.quantity) <= 0
            )
        ]

        stock_items = []
        for balance in sorted(
            positive_balances,
            key=lambda row: Decimal(row.total_value),
            reverse=True,
        )[:8]:
            product = product_by_id.get(balance.product_id)
            if product is None:
                continue
            stock_items.append(
                {
                    "product_name": product.name,
                    "product_type": product.product_type,
                    "quantity": _num(balance.quantity),
                    "base_unit": product.base_unit,
                    "avg_unit_cost": _num(balance.avg_unit_cost),
                    "total_value": _num(balance.total_value),
                }
            )

        unit_summaries.append(
            {
                "unit_code": unit.code,
                "unit_name": unit.name,
                "inventory_value": _num(
                    sum((Decimal(row.total_value) for row in unit_balances), Decimal("0"))
                ),
                "stocked_products": len(positive_balances),
                "zero_raw_material_count": len(zero_raw_materials),
                "zero_raw_materials": zero_raw_materials,
                "pending_manager": sum(
                    1 for row in unit_events if row.status == EventStatus.WAITING_MANAGER.value
                ),
                "waiting_complement": sum(
                    1 for row in unit_events if row.status == EventStatus.WAITING_COMPLEMENT.value
                ),
                "latest_event_at": unit_events[0].received_at.isoformat() if unit_events else None,
                "latest_production_at": (
                    unit_productions[0].created_at.isoformat() if unit_productions else None
                ),
                "stock_items": stock_items,
            }
        )

    attention_items = []
    for event in waiting_manager:
        attention_items.append(
            {
                "kind": "manager",
                "event_id": event.id,
                "unit_code": next((unit.code for unit in units if unit.id == event.unit_id), None),
                "received_at": event.received_at.isoformat(),
                "channel": event.channel,
                "event_type": event.event_type,
                "source_original": event.source_original,
                "reason": _event_reason(session, event.id),
            }
        )
    for event in waiting_complement:
        attention_items.append(
            {
                "kind": "complement",
                "event_id": event.id,
                "unit_code": next((unit.code for unit in units if unit.id == event.unit_id), None),
                "received_at": event.received_at.isoformat(),
                "channel": event.channel,
                "event_type": event.event_type,
                "source_original": event.source_original,
                "reason": None,
            }
        )

    manager_details = {
        event.id: {
            "received_at": event.received_at.isoformat(),
            "channel": event.channel,
            "reason": _event_reason(session, event.id),
        }
        for event in waiting_manager
    }

    return {
        "summary": {
            "inventory_value": _num(inventory_value),
            "waiting_complement": len(waiting_complement),
            "production_count": (
                session.scalar(
                    select(func.count())
                    .select_from(ProductionBatch)
                    .where(ProductionBatch.organization_id == organization_id)
                )
                or 0
                if feed_mill_visible
                else 0
            ),
            "feed_mill_visible": feed_mill_visible,
        },
        "unit_summaries": unit_summaries,
        "attention_items": attention_items,
        "manager_details": manager_details,
    }
