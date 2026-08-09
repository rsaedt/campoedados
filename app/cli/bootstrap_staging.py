from __future__ import annotations

import hashlib
import json
import os
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.enums import MembershipRole, ModuleCode
from app.models.channel import ChannelIdentity
from app.models.domain import (
    AccessToken,
    Membership,
    Organization,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.modules import seed_module_catalog, set_module_enabled


ALLOWED_MODULES = {item.value for item in ModuleCode}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Variável obrigatória ausente: {name}")
    return value


def _parse_json(name: str, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} contém JSON inválido: {exc}") from exc


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    # O bootstrap só roda quando explicitamente configurado no ambiente.
    if os.getenv("CAMPOEDADOS_BOOTSTRAP_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        print("staging bootstrap: disabled")
        return 0

    org_name = _required("CAMPOEDADOS_BOOTSTRAP_ORG_NAME")
    org_slug = _required("CAMPOEDADOS_BOOTSTRAP_ORG_SLUG")
    admin_name = _required("CAMPOEDADOS_BOOTSTRAP_ADMIN_NAME")
    admin_email = _required("CAMPOEDADOS_BOOTSTRAP_ADMIN_EMAIL")
    admin_token = _required("CAMPOEDADOS_BOOTSTRAP_ADMIN_TOKEN")
    units = _parse_json("CAMPOEDADOS_BOOTSTRAP_UNITS_JSON", [])
    if not units:
        raise RuntimeError("CAMPOEDADOS_BOOTSTRAP_UNITS_JSON precisa conter ao menos uma unidade.")

    modules = [
        item.strip()
        for item in os.getenv("CAMPOEDADOS_BOOTSTRAP_MODULES", "").split(",")
        if item.strip()
    ]
    invalid = set(modules) - ALLOWED_MODULES
    if invalid:
        raise RuntimeError(f"Módulos inválidos no bootstrap: {sorted(invalid)}")

    with SessionLocal() as session:
        seed_module_catalog(session)

        org = session.scalar(select(Organization).where(Organization.slug == org_slug))
        if org is None:
            org = Organization(name=org_name, slug=org_slug, active=True)
            session.add(org)
            session.flush()
        else:
            org.name = org_name
            org.active = True

        user = session.scalar(select(User).where(User.email == admin_email))
        if user is None:
            user = User(display_name=admin_name, email=admin_email, active=True)
            session.add(user)
            session.flush()
        else:
            user.display_name = admin_name
            user.active = True

        membership = session.scalar(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            membership = Membership(
                organization_id=org.id,
                user_id=user.id,
                role=MembershipRole.ADMIN.value,
                active=True,
            )
            session.add(membership)
            session.flush()
        else:
            membership.role = MembershipRole.ADMIN.value
            membership.active = True

        units_by_code: dict[str, Unit] = {}
        for item in units:
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", code)).strip()
            if not code:
                raise RuntimeError("Cada unidade do bootstrap precisa de code.")
            unit = session.scalar(
                select(Unit).where(Unit.organization_id == org.id, Unit.code == code)
            )
            if unit is None:
                unit = Unit(organization_id=org.id, code=code, name=name, active=True)
                session.add(unit)
                session.flush()
            else:
                unit.name = name
                unit.active = True
            units_by_code[code] = unit

        for module_code in ALLOWED_MODULES:
            enabled = module_code in modules
            set_module_enabled(session, org.id, module_code, enabled)
            permission = session.scalar(
                select(UserModulePermission).where(
                    UserModulePermission.membership_id == membership.id,
                    UserModulePermission.module_code == module_code,
                )
            )
            if permission is None:
                permission = UserModulePermission(
                    membership_id=membership.id,
                    module_code=module_code,
                    can_view=enabled,
                    can_register=enabled,
                    can_approve=enabled,
                    can_configure=enabled,
                )
                session.add(permission)
            else:
                permission.can_view = enabled
                permission.can_register = enabled
                permission.can_approve = enabled
                permission.can_configure = enabled

        token_hash = _token_hash(admin_token)
        existing_token = session.scalar(
            select(AccessToken).where(AccessToken.token_hash == token_hash)
        )
        if existing_token is None:
            issue_access_token(
                session,
                membership_id=membership.id,
                label="staging-bootstrap-admin",
                raw_token=admin_token,
            )

        identities = _parse_json("CAMPOEDADOS_BOOTSTRAP_CHANNEL_IDENTITIES_JSON", [])
        for item in identities:
            channel = str(item.get("channel", "")).strip()
            account_key = str(item.get("account_key", "default")).strip() or "default"
            external_user_id = str(item.get("external_user_id", "")).strip()
            unit_code = str(item.get("default_unit_code", "")).strip()
            if not channel or not external_user_id or unit_code not in units_by_code:
                raise RuntimeError(
                    "Identidade de canal precisa de channel, external_user_id e default_unit_code válido."
                )
            identity = session.scalar(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == channel,
                    ChannelIdentity.account_key == account_key,
                    ChannelIdentity.external_user_id == external_user_id,
                )
            )
            if identity is None:
                identity = ChannelIdentity(
                    membership_id=membership.id,
                    default_unit_id=units_by_code[unit_code].id,
                    channel=channel,
                    account_key=account_key,
                    external_user_id=external_user_id,
                    external_chat_id=item.get("external_chat_id"),
                    display_name=item.get("display_name") or admin_name,
                    active=True,
                )
                session.add(identity)
            else:
                identity.membership_id = membership.id
                identity.default_unit_id = units_by_code[unit_code].id
                identity.external_chat_id = item.get("external_chat_id")
                identity.display_name = item.get("display_name") or admin_name
                identity.active = True

        session.commit()
        print(f"staging bootstrap: organization={org.slug}")
        print(f"staging bootstrap: admin={admin_email}")
        print(f"staging bootstrap: units={','.join(sorted(units_by_code))}")
        print(f"staging bootstrap: modules={','.join(sorted(modules)) or 'none'}")
        print(f"staging bootstrap: channel_identities={len(identities)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        raise
