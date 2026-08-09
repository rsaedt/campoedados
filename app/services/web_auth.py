from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import MembershipRole
from app.models.auth import UserCredential
from app.models.domain import AccessToken, Membership, Organization, User
from app.services.auth import AuthenticationError, Principal, issue_access_token


SESSION_COOKIE = "campoedados_session"
SESSION_HOURS = 12
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


class FirstAccessError(AuthenticationError):
    pass


@dataclass(frozen=True)
class WebLoginResult:
    principal: Principal
    raw_session: str
    expires_at: datetime


def normalize_login_name(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) < 3 or len(normalized) > 120:
        raise AuthenticationError("Usuário deve ter entre 3 e 120 caracteres.")
    if any(ch.isspace() for ch in normalized):
        raise AuthenticationError("Usuário não pode conter espaços.")
    return normalized


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthenticationError("A senha deve ter pelo menos 8 caracteres.")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(derived.hex(), expected_hex)
    except Exception:
        return False


def set_user_credentials(
    session: Session,
    *,
    user_id: str,
    login_name: str,
    password: str,
) -> UserCredential:
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise AuthenticationError("Usuário inexistente ou inativo.")

    normalized = normalize_login_name(login_name)
    existing_login = session.scalar(
        select(UserCredential).where(UserCredential.login_name == normalized)
    )
    existing_user = session.get(UserCredential, user_id)
    if existing_login is not None and existing_login.user_id != user_id:
        raise AuthenticationError("Este nome de usuário já está em uso.")

    encoded = hash_password(password)
    if existing_user is None:
        row = UserCredential(
            user_id=user_id,
            login_name=normalized,
            password_hash=encoded,
        )
        session.add(row)
    else:
        existing_user.login_name = normalized
        existing_user.password_hash = encoded
        row = existing_user
    session.flush()
    return row


def _active_memberships(session: Session, user_id: str) -> list[tuple[Membership, Organization]]:
    return list(
        session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(
                Membership.user_id == user_id,
                Membership.active.is_(True),
                Organization.active.is_(True),
            )
            .order_by(Organization.name)
        ).all()
    )


def login_with_password(
    session: Session,
    *,
    login_name: str,
    password: str,
    organization_slug: str | None = None,
) -> WebLoginResult:
    normalized = normalize_login_name(login_name)
    credential = session.scalar(
        select(UserCredential).where(UserCredential.login_name == normalized)
    )
    if credential is None or not verify_password(password, credential.password_hash):
        raise AuthenticationError("Usuário ou senha inválidos.")

    user = session.get(User, credential.user_id)
    if user is None or not user.active:
        raise AuthenticationError("Usuário inativo.")

    memberships = _active_memberships(session, user.id)
    if organization_slug:
        slug = organization_slug.strip().casefold()
        memberships = [row for row in memberships if row[1].slug.casefold() == slug]
    if not memberships:
        raise AuthenticationError("Usuário sem vínculo ativo com a organização.")
    if len(memberships) > 1:
        raise AuthenticationError("Usuário possui acesso a mais de uma organização; selecione a organização.")

    membership, organization = memberships[0]
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    token, raw = issue_access_token(
        session,
        membership_id=membership.id,
        label="web-session",
        expires_at=expires_at,
    )
    principal = Principal(token_id=token.id, user=user, membership=membership, organization=organization)
    return WebLoginResult(principal=principal, raw_session=raw, expires_at=expires_at)


def configure_first_access(
    session: Session,
    *,
    organization_slug: str,
    admin_name: str,
    login_name: str,
    password: str,
) -> WebLoginResult:
    environment = os.getenv("CAMPOEDADOS_ENV", "development").strip().lower()
    if environment not in {"development", "staging", "test"}:
        raise FirstAccessError("Primeiro acesso público não está disponível neste ambiente.")

    org = session.scalar(
        select(Organization).where(
            Organization.slug == organization_slug.strip(),
            Organization.active.is_(True),
        )
    )
    if org is None:
        raise FirstAccessError("Organização não encontrada.")

    admin_rows = list(
        session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == org.id,
                Membership.role == MembershipRole.ADMIN.value,
                Membership.active.is_(True),
                User.active.is_(True),
            )
        ).all()
    )
    if any(session.get(UserCredential, user.id) is not None for _, user in admin_rows):
        raise FirstAccessError("O primeiro acesso desta organização já foi configurado.")

    matches = [row for row in admin_rows if row[1].display_name.casefold() == admin_name.strip().casefold()]
    if len(matches) != 1:
        raise FirstAccessError("Administrador não encontrado para esta organização.")

    membership, user = matches[0]
    set_user_credentials(
        session,
        user_id=user.id,
        login_name=login_name,
        password=password,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    token, raw = issue_access_token(
        session,
        membership_id=membership.id,
        label="web-session:first-access",
        expires_at=expires_at,
    )
    principal = Principal(token_id=token.id, user=user, membership=membership, organization=org)
    return WebLoginResult(principal=principal, raw_session=raw, expires_at=expires_at)


def revoke_web_session(session: Session, *, token_id: str) -> None:
    token = session.get(AccessToken, token_id)
    if token is None or token.revoked_at is not None:
        return
    if token.label and token.label.startswith("web-session"):
        token.revoked_at = datetime.now(timezone.utc)
        session.flush()
