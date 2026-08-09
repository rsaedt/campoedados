from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ModuleCode
from app.models.domain import OrganizationModule, SystemModule


DEFAULT_MODULES = {
    ModuleCode.LIVESTOCK.value: "Pecuária",
    ModuleCode.FEED_MILL.value: "Fábrica de Ração",
    ModuleCode.FINANCE.value: "Financeiro",
}


class ModuleNotEnabledError(RuntimeError):
    pass


def seed_module_catalog(session: Session) -> None:
    for code, name in DEFAULT_MODULES.items():
        if session.get(SystemModule, code) is None:
            session.add(SystemModule(code=code, name=name, active=True))
    session.flush()


def set_module_enabled(session: Session, organization_id: str, module_code: str, enabled: bool = True) -> OrganizationModule:
    seed_module_catalog(session)
    row = session.scalar(
        select(OrganizationModule).where(
            OrganizationModule.organization_id == organization_id,
            OrganizationModule.module_code == module_code,
        )
    )
    if row is None:
        row = OrganizationModule(
            organization_id=organization_id,
            module_code=module_code,
            enabled=enabled,
        )
        session.add(row)
    else:
        row.enabled = enabled
    session.flush()
    return row


def module_enabled(session: Session, organization_id: str, module_code: str) -> bool:
    return bool(
        session.scalar(
            select(OrganizationModule.enabled).where(
                OrganizationModule.organization_id == organization_id,
                OrganizationModule.module_code == module_code,
            )
        )
    )


def require_module(session: Session, organization_id: str, module_code: str) -> None:
    if not module_enabled(session, organization_id, module_code):
        raise ModuleNotEnabledError(f"Módulo '{module_code}' não está habilitado para a organização.")
