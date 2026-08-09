from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import UserModulePermission
from app.services.auth import Principal
from app.services.modules import require_module


class PermissionDeniedError(RuntimeError):
    pass


def require_module_permission(
    session: Session,
    principal: Principal,
    module_code: str,
    permission: str,
) -> UserModulePermission:
    require_module(session, principal.organization_id, module_code)
    row = session.scalar(
        select(UserModulePermission).where(
            UserModulePermission.membership_id == principal.membership.id,
            UserModulePermission.module_code == module_code,
        )
    )
    if row is None or not bool(getattr(row, permission, False)):
        raise PermissionDeniedError(
            f"Usuário não possui permissão '{permission}' no módulo '{module_code}'."
        )
    return row
