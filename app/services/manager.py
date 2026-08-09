from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventStatus, ModuleCode, TransferStatus
from app.models.domain import Approval, Event, EventModuleTarget, Purchase, Transfer, Unit
from app.schemas.manager import ManagerDecisionResponse, PendingEventItem
from app.services.audit import record_audit
from app.services.auth import Principal
from app.services.feed_mill import receive_transfer
from app.services.finance import approve_purchase, reject_purchase
from app.services.permissions import PermissionDeniedError, require_module_permission


class ManagerEventError(RuntimeError):
    pass


def _pending_targets(session: Session, event_id: str) -> list[EventModuleTarget]:
    return list(
        session.scalars(
            select(EventModuleTarget).where(
                EventModuleTarget.event_id == event_id,
                EventModuleTarget.status == EventStatus.WAITING_MANAGER.value,
                EventModuleTarget.requires_approval.is_(True),
            )
        )
    )


def _recompute_event_status(session: Session, event: Event) -> None:
    targets = list(session.scalars(select(EventModuleTarget).where(EventModuleTarget.event_id == event.id)))
    if any(row.status == EventStatus.WAITING_MANAGER.value for row in targets):
        event.status = EventStatus.WAITING_MANAGER.value
        event.requires_approval = True
    elif any(row.status == EventStatus.REJECTED.value for row in targets):
        event.status = EventStatus.REJECTED.value
        event.requires_approval = False
    else:
        event.status = EventStatus.PROCESSED.value
        event.requires_approval = False
    session.flush()


def list_pending_events(session: Session, *, principal: Principal) -> list[PendingEventItem]:
    rows = list(
        session.scalars(
            select(Event)
            .where(
                Event.organization_id == principal.organization_id,
                Event.status == EventStatus.WAITING_MANAGER.value,
            )
            .order_by(Event.received_at.asc())
        )
    )
    items: list[PendingEventItem] = []
    for event in rows:
        targets = _pending_targets(session, event.id)
        visible_targets = []
        for target in targets:
            try:
                require_module_permission(session, principal, target.module_code, "can_approve")
            except PermissionDeniedError:
                continue
            visible_targets.append(target)
        if not visible_targets:
            continue
        unit = session.get(Unit, event.unit_id) if event.unit_id else None
        items.append(
            PendingEventItem(
                event_id=event.id,
                event_type=event.event_type or "unclassified",
                status=event.status,
                unit_code=unit.code if unit else None,
                source_original=event.source_original,
                requires_approval=event.requires_approval,
                module_states=[
                    {
                        "module_code": row.module_code,
                        "status": row.status,
                        "requires_approval": row.requires_approval,
                    }
                    for row in visible_targets
                ],
            )
        )
    return items


def decide_event(
    session: Session,
    *,
    principal: Principal,
    event_id: str,
    decision: str,
    notes: str | None = None,
    accepted_quantity=None,
) -> ManagerDecisionResponse:
    event = session.get(Event, event_id)
    if event is None or event.organization_id != principal.organization_id:
        raise ManagerEventError("Evento gerencial não encontrado para a organização.")

    targets = _pending_targets(session, event.id)
    if not targets:
        raise ManagerEventError("Evento não possui módulos aguardando aprovação gerencial.")

    for target in targets:
        require_module_permission(session, principal, target.module_code, "can_approve")

    processed_modules: list[str] = []
    for target in targets:
        if target.module_code == ModuleCode.FINANCE.value:
            purchase = session.scalar(select(Purchase).where(Purchase.event_id == event.id))
            if purchase is None:
                raise ManagerEventError("Compra financeira vinculada ao evento não encontrada.")
            if decision == "approve":
                approve_purchase(
                    session,
                    organization_id=principal.organization_id,
                    purchase_id=purchase.id,
                )
                target.status = EventStatus.PROCESSED.value
            else:
                reject_purchase(
                    session,
                    organization_id=principal.organization_id,
                    purchase_id=purchase.id,
                )
                target.status = EventStatus.REJECTED.value
            target.requires_approval = False
            processed_modules.append(target.module_code)

        elif target.module_code == ModuleCode.FEED_MILL.value:
            transfer = session.scalar(
                select(Transfer).where(
                    Transfer.receipt_event_id == event.id,
                    Transfer.status == TransferStatus.DIVERGENT.value,
                )
            )
            if transfer is not None and decision == "approve":
                receive_transfer(
                    session,
                    organization_id=principal.organization_id,
                    transfer_id=transfer.id,
                    event_id=event.id,
                    received_quantity=accepted_quantity or transfer.received_quantity,
                    approve_divergence=True,
                )
                target.status = EventStatus.PROCESSED.value
            elif decision == "approve":
                # Não conformidade de recebimento já está refletida no estoque físico; aprovação apenas fecha a exceção.
                target.status = EventStatus.PROCESSED.value
            else:
                target.status = EventStatus.REJECTED.value
            target.requires_approval = False
            processed_modules.append(target.module_code)

        session.add(
            Approval(
                event_id=event.id,
                module_code=target.module_code,
                approver_user_id=principal.user_id,
                decision=decision,
                notes=notes,
            )
        )
        record_audit(
            session,
            organization_id=principal.organization_id,
            event_id=event.id,
            actor_user_id=principal.user_id,
            action=f"manager_{decision}",
            details={"module_code": target.module_code, "notes": notes},
        )

    _recompute_event_status(session, event)
    return ManagerDecisionResponse(
        event_id=event.id,
        status=event.status,
        decision=decision,
        processed_modules=processed_modules,
    )
