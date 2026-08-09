from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import ChannelAccount, ChannelContactRequest
from app.models.domain import Membership, Unit
from app.schemas.channels import ChannelIdentityCreate
from app.services.auth import Principal
from app.services.channel_identity import create_channel_identity, require_channel_admin
from app.services.channels.base import InboundChannelMessage
from app.models.domain import utcnow


class ChannelContactRequestError(RuntimeError):
    pass


def record_unknown_contact(session: Session, inbound: InboundChannelMessage) -> ChannelContactRequest | None:
    account = session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == inbound.channel,
            ChannelAccount.account_key == inbound.account_key,
            ChannelAccount.active.is_(True),
        )
    )
    if account is None:
        return None

    row = session.scalar(
        select(ChannelContactRequest).where(
            ChannelContactRequest.channel == inbound.channel,
            ChannelContactRequest.account_key == inbound.account_key,
            ChannelContactRequest.external_user_id == inbound.external_user_id,
        )
    )
    if row is None:
        row = ChannelContactRequest(
            organization_id=account.organization_id,
            channel=inbound.channel,
            account_key=inbound.account_key,
            external_user_id=inbound.external_user_id,
            external_chat_id=inbound.external_chat_id,
            display_name=inbound.display_name,
            last_message=inbound.text or None,
            status="pending",
        )
        session.add(row)
    else:
        row.external_chat_id = inbound.external_chat_id
        row.display_name = inbound.display_name or row.display_name
        row.last_message = inbound.text or row.last_message
        row.last_seen_at = utcnow()
        if row.status != "linked":
            row.status = "pending"
    session.flush()
    return row


def list_pending_contacts(session: Session, *, principal: Principal) -> list[ChannelContactRequest]:
    require_channel_admin(principal)
    return list(
        session.scalars(
            select(ChannelContactRequest)
            .where(
                ChannelContactRequest.organization_id == principal.organization_id,
                ChannelContactRequest.status == "pending",
            )
            .order_by(ChannelContactRequest.last_seen_at.desc())
        )
    )


def link_contact(
    session: Session,
    *,
    principal: Principal,
    request_id: str,
    membership_id: str,
    default_unit_code: str,
):
    require_channel_admin(principal)
    request = session.get(ChannelContactRequest, request_id)
    if request is None or request.organization_id != principal.organization_id:
        raise ChannelContactRequestError("Contato pendente não encontrado.")
    if request.status == "linked":
        raise ChannelContactRequestError("Este contato já foi vinculado.")

    membership = session.get(Membership, membership_id)
    if membership is None or membership.organization_id != principal.organization_id or not membership.active:
        raise ChannelContactRequestError("Usuário/vínculo inválido para esta organização.")
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == principal.organization_id,
            Unit.code == default_unit_code,
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise ChannelContactRequestError("Unidade padrão inválida.")

    identity = create_channel_identity(
        session,
        principal=principal,
        payload=ChannelIdentityCreate(
            membership_id=membership.id,
            default_unit_code=unit.code,
            channel=request.channel,
            account_key=request.account_key,
            external_user_id=request.external_user_id,
            external_chat_id=request.external_chat_id,
            display_name=request.display_name,
        ),
    )
    request.status = "linked"
    request.linked_identity_id = identity.id
    request.linked_at = utcnow()
    session.flush()
    return identity
