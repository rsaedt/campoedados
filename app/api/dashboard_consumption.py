from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.core.enums import ModuleCode
from app.models.consumption import ConsumptionRecord
from app.models.domain import Event, Product, Unit
from app.services.auth import Principal
from app.services.permissions import PermissionDeniedError, require_module_permission


router = APIRouter(prefix="/v1/dashboard/stock", tags=["dashboard-stock"])


def _num(value) -> float:
    return float(value or 0)


def _require_stock_visibility(session: Session, principal: Principal) -> None:
    for module_code in (ModuleCode.FEED_MILL.value, ModuleCode.LIVESTOCK.value):
        try:
            require_module_permission(session, principal, module_code, "can_view")
            return
        except PermissionDeniedError:
            continue
    raise HTTPException(status_code=403, detail="Estoque não disponível para este usuário.")


@router.get("/consumptions")
def stock_consumptions(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    _require_stock_visibility(session, principal)
    organization_id = principal.organization_id

    rows = list(
        session.scalars(
            select(ConsumptionRecord)
            .where(ConsumptionRecord.organization_id == organization_id)
            .order_by(ConsumptionRecord.created_at.desc())
            .limit(200)
        )
    )
    units = {
        row.id: row
        for row in session.scalars(
            select(Unit).where(Unit.organization_id == organization_id)
        )
    }
    products = {
        row.id: row
        for row in session.scalars(
            select(Product).where(Product.organization_id == organization_id)
        )
    }
    event_ids = [row.event_id for row in rows]
    events = (
        {
            row.id: row
            for row in session.scalars(select(Event).where(Event.id.in_(event_ids)))
        }
        if event_ids
        else {}
    )

    purpose_totals: dict[str, dict] = {}
    product_totals: dict[str, dict] = {}
    total_value = Decimal("0")

    for row in rows:
        total_value += Decimal(row.total_value)
        purpose = purpose_totals.setdefault(
            row.purpose_code,
            {
                "purpose_code": row.purpose_code,
                "purpose_label": row.purpose_label,
                "records": 0,
                "total_value": Decimal("0"),
            },
        )
        purpose["records"] += 1
        purpose["total_value"] += Decimal(row.total_value)

        product = products.get(row.product_id)
        product_key = row.product_id
        ptotal = product_totals.setdefault(
            product_key,
            {
                "product_id": row.product_id,
                "product_name": product.name if product else row.product_id,
                "base_unit": product.base_unit if product else "",
                "quantity": Decimal("0"),
                "total_value": Decimal("0"),
            },
        )
        ptotal["quantity"] += Decimal(row.quantity)
        ptotal["total_value"] += Decimal(row.total_value)

    return {
        "summary": {
            "records": len(rows),
            "total_value": _num(total_value),
        },
        "by_purpose": [
            {
                **item,
                "total_value": _num(item["total_value"]),
            }
            for item in sorted(
                purpose_totals.values(),
                key=lambda item: item["total_value"],
                reverse=True,
            )
        ],
        "by_product": [
            {
                **item,
                "quantity": _num(item["quantity"]),
                "total_value": _num(item["total_value"]),
            }
            for item in sorted(
                product_totals.values(),
                key=lambda item: item["total_value"],
                reverse=True,
            )
        ],
        "consumptions": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "unit_code": units[row.unit_id].code if row.unit_id in units else row.unit_id,
                "unit_name": units[row.unit_id].name if row.unit_id in units else "",
                "product_id": row.product_id,
                "product_name": products[row.product_id].name if row.product_id in products else row.product_id,
                "base_unit": products[row.product_id].base_unit if row.product_id in products else "",
                "quantity": _num(row.quantity),
                "unit_cost": _num(row.unit_cost),
                "total_value": _num(row.total_value),
                "purpose_code": row.purpose_code,
                "purpose_label": row.purpose_label,
                "context_label": row.context_label,
                "channel": events[row.event_id].channel if row.event_id in events else None,
                "source_original": events[row.event_id].source_original if row.event_id in events else None,
            }
            for row in rows
        ],
    }
