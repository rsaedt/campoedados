from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.models.channel import ChannelIdentity
from app.models.domain import Membership, Unit, User
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.channel_identity import ChannelIdentityAdminError, require_channel_admin


router = APIRouter(prefix="/v1/dashboard/contacts", tags=["dashboard-channel-links"])


class ChannelLinkUpdateRequest(BaseModel):
    membership_id: str
    default_unit_code: str = Field(min_length=1, max_length=40)


def _organization_identity(session: Session, *, principal: Principal, identity_id: str) -> ChannelIdentity:
    identity = session.get(ChannelIdentity, identity_id)
    if identity is None:
        raise ChannelIdentityAdminError("Vínculo de canal não encontrado.")
    membership = session.get(Membership, identity.membership_id)
    if membership is None or membership.organization_id != principal.organization_id:
        raise ChannelIdentityAdminError("Vínculo de canal não pertence a esta organização.")
    return identity


@router.get("/linked")
def list_linked_contacts(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        require_channel_admin(principal)
        rows = session.execute(
            select(ChannelIdentity, Membership, User, Unit)
            .join(Membership, Membership.id == ChannelIdentity.membership_id)
            .join(User, User.id == Membership.user_id)
            .join(Unit, Unit.id == ChannelIdentity.default_unit_id)
            .where(
                Membership.organization_id == principal.organization_id,
                ChannelIdentity.active.is_(True),
            )
            .order_by(ChannelIdentity.channel, ChannelIdentity.account_key, User.display_name)
        ).all()
        return [
            {
                "id": identity.id,
                "channel": identity.channel,
                "account_key": identity.account_key,
                "external_user_id": identity.external_user_id,
                "display_name": identity.display_name or user.display_name,
                "membership_id": membership.id,
                "user_name": user.display_name,
                "default_unit_code": unit.code,
                "default_unit_name": unit.name,
            }
            for identity, membership, user, unit in rows
        ]
    except ChannelIdentityAdminError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/linked/{identity_id}")
def update_linked_contact(
    identity_id: str,
    payload: ChannelLinkUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        require_channel_admin(principal)
        identity = _organization_identity(session, principal=principal, identity_id=identity_id)

        membership = session.get(Membership, payload.membership_id)
        if (
            membership is None
            or membership.organization_id != principal.organization_id
            or not membership.active
        ):
            raise ChannelIdentityAdminError("Usuário/vínculo inválido para esta organização.")

        unit = session.scalar(
            select(Unit).where(
                Unit.organization_id == principal.organization_id,
                Unit.code == payload.default_unit_code,
                Unit.active.is_(True),
            )
        )
        if unit is None:
            raise ChannelIdentityAdminError("Unidade padrão inválida para esta organização.")

        old_membership_id = identity.membership_id
        old_unit_id = identity.default_unit_id
        old_unit = session.get(Unit, old_unit_id)

        identity.membership_id = membership.id
        identity.default_unit_id = unit.id
        session.flush()

        record_audit(
            session,
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action="channel_contact_link_updated",
            details={
                "identity_id": identity.id,
                "channel": identity.channel,
                "account_key": identity.account_key,
                "old_membership_id": old_membership_id,
                "new_membership_id": membership.id,
                "old_unit_code": old_unit.code if old_unit is not None else None,
                "new_unit_code": unit.code,
            },
        )
        session.commit()
        return {
            "ok": True,
            "identity_id": identity.id,
            "membership_id": membership.id,
            "default_unit_code": unit.code,
        }
    except ChannelIdentityAdminError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
