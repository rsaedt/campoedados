from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import MembershipRole
from app.models.channel import ChannelIdentity
from app.models.domain import Membership, Organization, Unit, User
from app.schemas.channels import ChannelIdentityCreate
from app.services.auth import Principal


class UnknownChannelIdentityError(RuntimeError):
    pass


class ChannelIdentityAdminError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedChannelIdentity:
    identity: ChannelIdentity
    principal: Principal
    unit: Unit


def resolve_channel_identity(
    session: Session,
    *,
    channel: str,
    account_key: str,
    external_user_id: str,
) -> ResolvedChannelIdentity:
    identity = session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == channel,
            ChannelIdentity.account_key == account_key,
            ChannelIdentity.external_user_id == external_user_id,
            ChannelIdentity.active.is_(True),
        )
    )
    if identity is None:
        raise UnknownChannelIdentityError("Contato não cadastrado para este canal.")

    membership = session.get(Membership, identity.membership_id)
    if membership is None or not membership.active:
        raise UnknownChannelIdentityError("Vínculo do contato está inativo.")

    user = session.get(User, membership.user_id)
    organization = session.get(Organization, membership.organization_id)
    unit = session.get(Unit, identity.default_unit_id)
    if (
        user is None
        or not user.active
        or organization is None
        or not organization.active
        or unit is None
        or not unit.active
        or unit.organization_id != organization.id
    ):
        raise UnknownChannelIdentityError("Cadastro do contato está incompleto ou inativo.")

    principal = Principal(
        token_id=f"channel:{identity.id}",
        user=user,
        membership=membership,
        organization=organization,
    )
    return ResolvedChannelIdentity(identity=identity, principal=principal, unit=unit)


def require_channel_admin(principal: Principal) -> None:
    if principal.membership.role != MembershipRole.ADMIN.value:
        raise ChannelIdentityAdminError("Somente administradores podem configurar identidades de canal.")


def create_channel_identity(
    session: Session,
    *,
    principal: Principal,
    payload: ChannelIdentityCreate,
) -> ChannelIdentity:
    require_channel_admin(principal)
    membership = session.get(Membership, payload.membership_id)
    if membership is None or membership.organization_id != principal.organization_id:
        raise ChannelIdentityAdminError("Vínculo não pertence à organização do administrador.")
    unit = session.scalar(
        select(Unit).where(
            Unit.organization_id == principal.organization_id,
            Unit.code == payload.default_unit_code,
            Unit.active.is_(True),
        )
    )
    if unit is None:
        raise ChannelIdentityAdminError("Unidade padrão não encontrada para a organização.")

    existing = session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == payload.channel,
            ChannelIdentity.account_key == payload.account_key,
            ChannelIdentity.external_user_id == payload.external_user_id,
        )
    )
    if existing is not None:
        raise ChannelIdentityAdminError("Este contato já está vinculado a este canal/conta.")

    row = ChannelIdentity(
        membership_id=membership.id,
        default_unit_id=unit.id,
        channel=payload.channel,
        account_key=payload.account_key,
        external_user_id=payload.external_user_id,
        external_chat_id=payload.external_chat_id,
        display_name=payload.display_name,
    )
    session.add(row)
    session.flush()
    return row


def list_channel_identities(session: Session, *, principal: Principal) -> list[tuple[ChannelIdentity, Unit]]:
    require_channel_admin(principal)
    rows = session.execute(
        select(ChannelIdentity, Unit)
        .join(Membership, Membership.id == ChannelIdentity.membership_id)
        .join(Unit, Unit.id == ChannelIdentity.default_unit_id)
        .where(Membership.organization_id == principal.organization_id)
        .order_by(ChannelIdentity.channel, ChannelIdentity.account_key, ChannelIdentity.external_user_id)
    ).all()
    return list(rows)
