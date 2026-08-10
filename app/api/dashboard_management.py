from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, MovementType
from app.models.domain import Event, EventModuleTarget, Product, Unit
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.inventory import get_balance, issue_stock, receive_stock
from app.services.permissions import PermissionDeniedError, require_module_permission


router = APIRouter(prefix="/v1/dashboard/management", tags=["dashboard-management"])


class StockCorrectionRequest(BaseModel):
    unit_code: str = Field(min_length=1, max_length=40)
    product_id: str
    target_quantity: Decimal = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    unit_cost: Decimal | None = Field(default=None, ge=0)


class CloseIncompleteEventRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _require_feed_mill_management(session: Session, principal: Principal) -> None:
    try:
        require_module_permission(session, principal, ModuleCode.FEED_MILL.value, "can_configure")
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="Correção de estoque não disponível para este usuário.") from exc


def _resolve_unit(session: Session, organization_id: str, code: str) -> Unit:
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == organization_id,
            Unit.code == code,
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise ValueError("Fazenda/unidade não encontrada.")
    return unit


@router.post("/stock/corrections", status_code=status.HTTP_201_CREATED)
def correct_stock(
    payload: StockCorrectionRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        _require_feed_mill_management(session, principal)
        unit = _resolve_unit(session, principal.organization_id, payload.unit_code)
        product = session.get(Product, payload.product_id)
        if product is None or product.organization_id != principal.organization_id or not product.active:
            raise ValueError("Produto não encontrado.")

        balance = get_balance(
            session,
            principal.organization_id,
            unit.id,
            product.id,
            create=True,
        )
        current_quantity = Decimal(balance.quantity)
        target_quantity = Decimal(payload.target_quantity)
        delta = target_quantity - current_quantity
        movement_id = None

        if delta < 0:
            movement, _ = issue_stock(
                session,
                organization_id=principal.organization_id,
                unit_id=unit.id,
                product_id=product.id,
                quantity=-delta,
                movement_type=MovementType.ADJUSTMENT.value,
                reference_type="manager_stock_correction",
            )
            movement_id = movement.id
        elif delta > 0:
            if current_quantity > 0:
                cost = Decimal(balance.avg_unit_cost)
            elif payload.unit_cost is not None:
                cost = Decimal(payload.unit_cost)
            else:
                raise ValueError(
                    "Para aumentar um estoque sem saldo anterior, informe o custo unitário da correção."
                )
            movement = receive_stock(
                session,
                organization_id=principal.organization_id,
                unit_id=unit.id,
                product_id=product.id,
                quantity=delta,
                unit_cost=cost,
                movement_type=MovementType.ADJUSTMENT.value,
                reference_type="manager_stock_correction",
            )
            movement_id = movement.id

        updated = get_balance(
            session,
            principal.organization_id,
            unit.id,
            product.id,
            create=False,
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="manager_stock_corrected",
            details={
                "movement_id": movement_id,
                "unit_code": unit.code,
                "product_id": product.id,
                "product_name": product.name,
                "previous_quantity": str(current_quantity),
                "target_quantity": str(target_quantity),
                "delta": str(delta),
                "reason": payload.reason,
            },
        )
        session.commit()
        return {
            "ok": True,
            "movement_id": movement_id,
            "unit_code": unit.code,
            "product_name": product.name,
            "previous_quantity": current_quantity,
            "target_quantity": Decimal(updated.quantity) if updated else Decimal("0"),
            "avg_unit_cost": Decimal(updated.avg_unit_cost) if updated else Decimal("0"),
        }
    except HTTPException:
        session.rollback()
        raise
    except (PermissionDeniedError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise


@router.post("/events/{event_id}/close")
def close_incomplete_event(
    event_id: str,
    payload: CloseIncompleteEventRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        event = session.get(Event, event_id)
        if event is None or event.organization_id != principal.organization_id:
            raise ValueError("Ocorrência não encontrada.")
        if event.status != EventStatus.WAITING_COMPLEMENT.value:
            raise ValueError("Somente ocorrências aguardando complemento podem ser encerradas por este fluxo.")

        targets = list(
            session.scalars(select(EventModuleTarget).where(EventModuleTarget.event_id == event.id))
        )
        if not targets:
            raise ValueError("Ocorrência sem módulo associado.")
        for target in targets:
            require_module_permission(session, principal, target.module_code, "can_approve")

        previous_status = event.status
        for target in targets:
            if target.status == EventStatus.WAITING_COMPLEMENT.value:
                target.status = EventStatus.REJECTED.value
                target.requires_approval = False
        event.status = EventStatus.REJECTED.value
        event.requires_approval = False

        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action="manager_incomplete_event_closed",
            details={
                "previous_status": previous_status,
                "final_status": EventStatus.REJECTED.value,
                "reason": payload.reason,
                "source_original": event.source_original,
            },
        )
        session.commit()
        return {"ok": True, "event_id": event.id, "status": event.status}
    except PermissionDeniedError as exc:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
