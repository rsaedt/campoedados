from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.core.enums import EventStatus, ModuleCode, MovementType
from app.models.channel import ChannelAccount, ChannelContactRequest, ChannelIdentity
from app.models.domain import (
    Event,
    InventoryBalance,
    Membership,
    OrganizationModule,
    Product,
    ProductionBatch,
    Recipe,
    SystemModule,
    Unit,
    User,
)
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.channel_contacts import ChannelContactRequestError, link_contact
from app.services.channel_identity import ChannelIdentityAdminError, require_channel_admin
from app.services.inventory import receive_stock
from app.services.manager import list_pending_events
from app.services.permissions import PermissionDeniedError, require_module_permission
from app.services.telegram_admin import TelegramAdminError, connect_telegram_bot


router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


class TelegramConnectRequest(BaseModel):
    account_key: str = Field(min_length=2, max_length=80)
    bot_token: str = Field(min_length=10, max_length=300)
    display_name: str | None = Field(default=None, max_length=180)


class ContactLinkRequest(BaseModel):
    membership_id: str
    default_unit_code: str = Field(min_length=1, max_length=40)


class InventoryAdjustmentRequest(BaseModel):
    unit_code: str = Field(min_length=1, max_length=40)
    product_id: str
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


def _num(value) -> float:
    return float(value or 0)


@router.get("/overview")
def dashboard_overview(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    organization_id = principal.organization_id

    units = list(
        session.scalars(
            select(Unit)
            .where(Unit.organization_id == organization_id, Unit.active.is_(True))
            .order_by(Unit.code)
        )
    )
    unit_by_id = {row.id: row for row in units}

    memberships = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id, Membership.active.is_(True), User.active.is_(True))
        .order_by(User.display_name)
    ).all()

    modules = session.execute(
        select(OrganizationModule, SystemModule)
        .join(SystemModule, SystemModule.code == OrganizationModule.module_code)
        .where(OrganizationModule.organization_id == organization_id, OrganizationModule.enabled.is_(True))
        .order_by(SystemModule.name)
    ).all()

    products = list(
        session.scalars(
            select(Product)
            .where(Product.organization_id == organization_id, Product.active.is_(True))
            .order_by(Product.name)
        )
    )
    product_by_id = {row.id: row for row in products}

    balances = list(
        session.scalars(
            select(InventoryBalance).where(InventoryBalance.organization_id == organization_id)
        )
    )

    events = list(
        session.scalars(
            select(Event)
            .where(Event.organization_id == organization_id)
            .order_by(Event.received_at.desc())
            .limit(50)
        )
    )

    pending = list_pending_events(session, principal=principal)

    productions = session.execute(
        select(ProductionBatch, Recipe)
        .join(Recipe, Recipe.id == ProductionBatch.recipe_id)
        .where(ProductionBatch.organization_id == organization_id)
        .order_by(ProductionBatch.created_at.desc())
        .limit(20)
    ).all()

    accounts = []
    contact_requests = []
    try:
        require_channel_admin(principal)
        accounts = list(
            session.scalars(
                select(ChannelAccount)
                .where(ChannelAccount.organization_id == organization_id)
                .order_by(ChannelAccount.channel, ChannelAccount.account_key)
            )
        )
        contact_requests = list(
            session.scalars(
                select(ChannelContactRequest)
                .where(
                    ChannelContactRequest.organization_id == organization_id,
                    ChannelContactRequest.status == "pending",
                )
                .order_by(ChannelContactRequest.last_seen_at.desc())
            )
        )
    except ChannelIdentityAdminError:
        pass

    event_total = session.scalar(
        select(func.count()).select_from(Event).where(Event.organization_id == organization_id)
    ) or 0
    processed_total = session.scalar(
        select(func.count()).select_from(Event).where(
            Event.organization_id == organization_id,
            Event.status == EventStatus.PROCESSED.value,
        )
    ) or 0

    return {
        "me": {
            "user_id": principal.user_id,
            "display_name": principal.user.display_name,
            "role": principal.membership.role,
            "organization_id": organization_id,
            "organization": principal.organization.name,
        },
        "summary": {
            "events": event_total,
            "processed": processed_total,
            "pending_manager": len(pending),
            "pending_contacts": len(contact_requests),
            "units": len(units),
            "products": len(products),
        },
        "modules": [
            {"code": org_module.module_code, "name": system_module.name}
            for org_module, system_module in modules
        ],
        "units": [{"id": row.id, "code": row.code, "name": row.name} for row in units],
        "memberships": [
            {
                "id": membership.id,
                "user_id": user.id,
                "display_name": user.display_name,
                "email": user.email,
                "role": membership.role,
            }
            for membership, user in memberships
        ],
        "products": [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "product_type": row.product_type,
                "base_unit": row.base_unit,
                "package_weight": _num(row.package_weight) if row.package_weight is not None else None,
            }
            for row in products
        ],
        "inventory": [
            {
                "unit_code": unit_by_id[row.unit_id].code if row.unit_id in unit_by_id else row.unit_id,
                "unit_name": unit_by_id[row.unit_id].name if row.unit_id in unit_by_id else "",
                "product_id": row.product_id,
                "product_name": product_by_id[row.product_id].name if row.product_id in product_by_id else row.product_id,
                "quantity": _num(row.quantity),
                "avg_unit_cost": _num(row.avg_unit_cost),
                "total_value": _num(row.total_value),
            }
            for row in balances
        ],
        "events": [
            {
                "id": row.id,
                "received_at": row.received_at.isoformat(),
                "unit_code": unit_by_id[row.unit_id].code if row.unit_id in unit_by_id else None,
                "channel": row.channel,
                "source_type": row.source_type,
                "source_original": row.source_original,
                "event_type": row.event_type,
                "status": row.status,
                "requires_approval": row.requires_approval,
                "confidence": _num(row.confidence) if row.confidence is not None else None,
            }
            for row in events
        ],
        "pending_manager": [item.model_dump(mode="json") for item in pending],
        "productions": [
            {
                "id": batch.id,
                "created_at": batch.created_at.isoformat(),
                "unit_code": unit_by_id[batch.unit_id].code if batch.unit_id in unit_by_id else batch.unit_id,
                "recipe_name": recipe.name,
                "batch_count": _num(batch.batch_count),
                "output_quantity": _num(batch.output_quantity),
                "total_material_cost": _num(batch.total_material_cost),
                "output_unit_cost": _num(batch.output_unit_cost),
            }
            for batch, recipe in productions
        ],
        "telegram_accounts": [
            {
                "id": row.id,
                "account_key": row.account_key,
                "display_name": row.display_name,
                "external_account_id": row.external_account_id,
                "active": row.active,
                "credential_configured": bool(row.credential_ciphertext and row.webhook_secret_ciphertext),
            }
            for row in accounts if row.channel == "telegram"
        ],
        "pending_contacts": [
            {
                "id": row.id,
                "channel": row.channel,
                "account_key": row.account_key,
                "external_user_id": row.external_user_id,
                "external_chat_id": row.external_chat_id,
                "display_name": row.display_name,
                "last_message": row.last_message,
                "first_seen_at": row.first_seen_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in contact_requests
        ],
    }


@router.post("/telegram/connect", status_code=status.HTTP_201_CREATED)
def dashboard_connect_telegram(
    payload: TelegramConnectRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        result = connect_telegram_bot(
            session,
            principal=principal,
            account_key=payload.account_key,
            bot_token=payload.bot_token,
            display_name=payload.display_name,
            public_base_url=str(request.base_url).rstrip("/"),
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="telegram_bot_connected",
            details={
                "account_key": result.account_key,
                "bot_id": result.bot_id,
                "bot_username": result.bot_username,
                "webhook_url": result.webhook_url,
            },
        )
        session.commit()
        return {
            "ok": True,
            "account_key": result.account_key,
            "display_name": result.display_name,
            "bot_username": result.bot_username,
            "webhook_url": result.webhook_url,
            "next_step": "Envie uma mensagem para o bot. O contato aparecerá no dashboard para vínculo.",
        }
    except (TelegramAdminError, ChannelIdentityAdminError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise


@router.post("/contacts/{request_id}/link")
def dashboard_link_contact(
    request_id: str,
    payload: ContactLinkRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        identity = link_contact(
            session,
            principal=principal,
            request_id=request_id,
            membership_id=payload.membership_id,
            default_unit_code=payload.default_unit_code,
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="channel_contact_linked",
            details={
                "identity_id": identity.id,
                "channel": identity.channel,
                "account_key": identity.account_key,
                "membership_id": identity.membership_id,
                "default_unit_code": payload.default_unit_code,
            },
        )
        session.commit()
        return {"ok": True, "identity_id": identity.id}
    except (ChannelContactRequestError, ChannelIdentityAdminError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/inventory/adjustments", status_code=status.HTTP_201_CREATED)
def dashboard_inventory_adjustment(
    payload: InventoryAdjustmentRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        require_module_permission(session, principal, ModuleCode.FEED_MILL.value, "can_configure")
        unit = session.scalar(
            select(Unit).where(
                Unit.organization_id == principal.organization_id,
                Unit.code == payload.unit_code,
                Unit.active.is_(True),
            )
        )
        product = session.get(Product, payload.product_id)
        if unit is None:
            raise ValueError("Unidade não encontrada.")
        if product is None or product.organization_id != principal.organization_id or not product.active:
            raise ValueError("Produto não encontrado.")

        movement = receive_stock(
            session,
            organization_id=principal.organization_id,
            unit_id=unit.id,
            product_id=product.id,
            quantity=payload.quantity,
            unit_cost=payload.unit_cost,
            movement_type=MovementType.ADJUSTMENT.value,
            reference_type="dashboard_adjustment",
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="inventory_adjustment",
            details={
                "movement_id": movement.id,
                "unit_code": unit.code,
                "product_id": product.id,
                "product_name": product.name,
                "quantity": str(payload.quantity),
                "unit_cost": str(payload.unit_cost),
                "note": payload.note,
            },
        )
        session.commit()
        return {"ok": True, "movement_id": movement.id}
    except (PermissionDeniedError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
