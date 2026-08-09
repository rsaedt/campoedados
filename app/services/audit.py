from sqlalchemy.orm import Session

from app.models.domain import AuditEntry


def record_audit(
    session: Session,
    *,
    organization_id: str,
    action: str,
    event_id: str | None = None,
    actor_user_id: str | None = None,
    details: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        organization_id=organization_id,
        event_id=event_id,
        actor_user_id=actor_user_id,
        action=action,
        details=details,
    )
    session.add(entry)
    session.flush()
    return entry
