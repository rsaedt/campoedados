from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import MembershipRole
from app.models.domain import (
    AuditEntry,
    Membership,
    Organization,
    Unit,
    User,
    UserModulePermission,
)
from app.services.auth import issue_access_token
from app.services.modules import DEFAULT_MODULES, seed_module_catalog, set_module_enabled


class OnboardingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnboardingUnit:
    code: str
    name: str


@dataclass(frozen=True)
class OnboardingResult:
    organization: Organization
    admin_user: User
    admin_membership: Membership
    units: tuple[Unit, ...]
    enabled_modules: tuple[str, ...]
    raw_admin_token: str


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")


def _normalize_units(units: Iterable[OnboardingUnit]) -> tuple[OnboardingUnit, ...]:
    normalized: list[OnboardingUnit] = []
    seen: set[str] = set()
    for item in units:
        code = item.code.strip().upper()
        name = item.name.strip()
        if not code or not name:
            raise OnboardingError("Cada unidade precisa de código e nome.")
        if code in seen:
            raise OnboardingError(f"Código de unidade duplicado no onboarding: {code}")
        seen.add(code)
        normalized.append(OnboardingUnit(code=code, name=name))
    if not normalized:
        raise OnboardingError("O onboarding precisa de ao menos uma unidade.")
    return tuple(normalized)


def onboard_organization(
    session: Session,
    *,
    organization_name: str,
    organization_slug: str,
    admin_name: str,
    admin_email: str | None,
    units: Iterable[OnboardingUnit],
    modules: Iterable[str],
) -> OnboardingResult:
    """Cria uma organização de forma transacional e emite o token admin uma única vez.

    A função deliberadamente não faz commit. O chamador controla a transação.
    Reexecução com o mesmo slug é recusada para evitar alteração silenciosa de cliente.
    """

    organization_name = organization_name.strip()
    organization_slug = organization_slug.strip().lower()
    admin_name = admin_name.strip()
    admin_email = admin_email.strip().lower() if admin_email and admin_email.strip() else None

    if not organization_name:
        raise OnboardingError("Nome da organização é obrigatório.")
    if not _SLUG_RE.fullmatch(organization_slug):
        raise OnboardingError(
            "Slug inválido. Use letras minúsculas, números e hífen, com 2 a 80 caracteres."
        )
    if not admin_name:
        raise OnboardingError("Nome do administrador é obrigatório.")

    normalized_units = _normalize_units(units)
    requested_modules = tuple(dict.fromkeys(item.strip() for item in modules if item.strip()))
    if not requested_modules:
        raise OnboardingError("Habilite ao menos um módulo no onboarding.")
    invalid_modules = sorted(set(requested_modules) - set(DEFAULT_MODULES))
    if invalid_modules:
        raise OnboardingError(f"Módulos inválidos: {', '.join(invalid_modules)}")

    if session.scalar(select(Organization).where(Organization.slug == organization_slug)) is not None:
        raise OnboardingError(f"Já existe organização com slug '{organization_slug}'.")

    seed_module_catalog(session)

    organization = Organization(
        name=organization_name,
        slug=organization_slug,
        active=True,
    )
    session.add(organization)
    session.flush()

    user = None
    if admin_email:
        user = session.scalar(select(User).where(User.email == admin_email))
    if user is None:
        user = User(display_name=admin_name, email=admin_email, active=True)
        session.add(user)
        session.flush()
    else:
        if not user.active:
            raise OnboardingError("O e-mail informado pertence a um usuário inativo.")
        user.display_name = admin_name

    membership = Membership(
        organization_id=organization.id,
        user_id=user.id,
        role=MembershipRole.ADMIN.value,
        active=True,
    )
    session.add(membership)
    session.flush()

    created_units: list[Unit] = []
    for item in normalized_units:
        unit = Unit(
            organization_id=organization.id,
            code=item.code,
            name=item.name,
            active=True,
        )
        session.add(unit)
        created_units.append(unit)
    session.flush()

    requested_set = set(requested_modules)
    for module_code in DEFAULT_MODULES:
        enabled = module_code in requested_set
        set_module_enabled(session, organization.id, module_code, enabled)
        session.add(
            UserModulePermission(
                membership_id=membership.id,
                module_code=module_code,
                can_view=enabled,
                can_register=enabled,
                can_approve=enabled,
                can_configure=enabled,
            )
        )

    _, raw_token = issue_access_token(
        session,
        membership_id=membership.id,
        label="organization-onboarding-admin",
    )

    session.add(
        AuditEntry(
            organization_id=organization.id,
            actor_user_id=user.id,
            action="organization_onboarded",
            details={
                "organization_slug": organization.slug,
                "admin_membership_id": membership.id,
                "unit_codes": [item.code for item in created_units],
                "enabled_modules": sorted(requested_set),
            },
        )
    )
    session.flush()

    return OnboardingResult(
        organization=organization,
        admin_user=user,
        admin_membership=membership,
        units=tuple(created_units),
        enabled_modules=tuple(sorted(requested_set)),
        raw_admin_token=raw_token,
    )
