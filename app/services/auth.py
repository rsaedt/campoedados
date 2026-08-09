from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import AccessToken, Membership, Organization, User


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Principal:
    token_id: str
    user: User
    membership: Membership
    organization: Organization

    @property
    def organization_id(self) -> str:
        return self.organization.id

    @property
    def user_id(self) -> str:
        return self.user.id


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def issue_access_token(
    session: Session,
    *,
    membership_id: str,
    label: str | None = None,
    expires_at: datetime | None = None,
    raw_token: str | None = None,
) -> tuple[AccessToken, str]:
    membership = session.get(Membership, membership_id)
    if membership is None or not membership.active:
        raise AuthenticationError("Vínculo de usuário inexistente ou inativo.")

    user = session.get(User, membership.user_id)
    organization = session.get(Organization, membership.organization_id)
    if user is None or not user.active or organization is None or not organization.active:
        raise AuthenticationError("Usuário ou organização inativos.")

    raw = raw_token or secrets.token_urlsafe(32)
    row = AccessToken(
        membership_id=membership_id,
        token_hash=_token_hash(raw),
        label=label,
        expires_at=expires_at,
    )
    session.add(row)
    session.flush()
    return row, raw


def authenticate_access_token(session: Session, raw_token: str) -> Principal:
    if not raw_token:
        raise AuthenticationError("Token ausente.")

    token = session.scalar(select(AccessToken).where(AccessToken.token_hash == _token_hash(raw_token)))
    if token is None or token.revoked_at is not None:
        raise AuthenticationError("Token inválido ou revogado.")
    if token.expires_at is not None and _as_utc(token.expires_at) <= datetime.now(timezone.utc):
        raise AuthenticationError("Token expirado.")

    membership = session.get(Membership, token.membership_id)
    if membership is None or not membership.active:
        raise AuthenticationError("Vínculo inativo.")
    user = session.get(User, membership.user_id)
    organization = session.get(Organization, membership.organization_id)
    if user is None or not user.active or organization is None or not organization.active:
        raise AuthenticationError("Usuário ou organização inativos.")

    return Principal(token_id=token.id, user=user, membership=membership, organization=organization)
