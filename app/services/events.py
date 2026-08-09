from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus
from app.models.domain import Event, EventModuleTarget
from app.services.modules import module_enabled


class NoEnabledTargetModuleError(RuntimeError):
    pass


def create_event(
    session: Session,
    *,
    organization_id: str,
    source_original: str,
    target_modules: list[str],
    unit_id: str | None = None,
    actor_user_id: str | None = None,
    channel: str = "internal",
    source_type: str = "text",
    event_type: str | None = None,
    interpretation: dict | None = None,
    confidence: Decimal | None = None,
    requires_approval: bool = False,
    correlation_id: str | None = None,
    require_target: bool = True,
) -> Event:
    enabled_targets = [
        code
        for code in dict.fromkeys(target_modules)
        if module_enabled(session, organization_id, code)
    ]
    if require_target and not enabled_targets:
        raise NoEnabledTargetModuleError("Nenhum dos módulos-alvo está habilitado para a organização.")

    event = Event(
        organization_id=organization_id,
        unit_id=unit_id,
        actor_user_id=actor_user_id,
        channel=channel,
        source_type=source_type,
        source_original=source_original,
        event_type=event_type,
        interpretation=interpretation,
        confidence=confidence,
        requires_approval=requires_approval,
        correlation_id=correlation_id,
    )
    session.add(event)
    session.flush()
    for code in enabled_targets:
        session.add(
            EventModuleTarget(
                event_id=event.id,
                module_code=code,
                status=EventStatus.RECEIVED.value,
            )
        )
    session.flush()
    return event


def enabled_event_targets(session: Session, event_id: str) -> list[EventModuleTarget]:
    return list(
        session.scalars(
            select(EventModuleTarget).where(EventModuleTarget.event_id == event_id)
        )
    )


def set_event_module_status(
    session: Session,
    *,
    event_id: str,
    module_code: str,
    status: str,
    requires_approval: bool | None = None,
) -> EventModuleTarget | None:
    row = session.scalar(
        select(EventModuleTarget).where(
            EventModuleTarget.event_id == event_id,
            EventModuleTarget.module_code == module_code,
        )
    )
    if row is None:
        return None
    row.status = status
    if requires_approval is not None:
        row.requires_approval = requires_approval
    session.flush()
    return row
