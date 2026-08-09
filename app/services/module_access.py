from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import OrganizationModule, SystemModule, UserModulePermission
from app.services.auth import Principal


@dataclass(frozen=True)
class AccessibleModule:
    code: str
    name: str
    can_view: bool
    can_register: bool
    can_approve: bool
    can_configure: bool


def accessible_modules(session: Session, principal: Principal) -> list[AccessibleModule]:
    """Módulos que a organização possui E que o usuário pode visualizar."""
    rows = session.execute(
        select(OrganizationModule, SystemModule, UserModulePermission)
        .join(SystemModule, SystemModule.code == OrganizationModule.module_code)
        .join(
            UserModulePermission,
            (UserModulePermission.module_code == OrganizationModule.module_code)
            & (UserModulePermission.membership_id == principal.membership.id),
        )
        .where(
            OrganizationModule.organization_id == principal.organization_id,
            OrganizationModule.enabled.is_(True),
            UserModulePermission.can_view.is_(True),
        )
        .order_by(SystemModule.name)
    ).all()
    return [
        AccessibleModule(
            code=org_module.module_code,
            name=system_module.name,
            can_view=permission.can_view,
            can_register=permission.can_register,
            can_approve=permission.can_approve,
            can_configure=permission.can_configure,
        )
        for org_module, system_module, permission in rows
    ]


def accessible_module_codes(session: Session, principal: Principal) -> set[str]:
    return {row.code for row in accessible_modules(session, principal)}
