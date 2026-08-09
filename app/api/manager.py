from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.schemas.manager import ManagerDecisionRequest, ManagerDecisionResponse, PendingEventItem
from app.services.auth import Principal
from app.services.manager import ManagerEventError, decide_event, list_pending_events
from app.services.modules import ModuleNotEnabledError
from app.services.permissions import PermissionDeniedError


router = APIRouter(prefix="/v1/manager", tags=["manager"])


@router.get("/pending", response_model=list[PendingEventItem])
def get_pending_events(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    return list_pending_events(session, principal=principal)


@router.post("/events/{event_id}/decision", response_model=ManagerDecisionResponse)
def post_manager_decision(
    event_id: str,
    payload: ManagerDecisionRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        result = decide_event(
            session,
            principal=principal,
            event_id=event_id,
            decision=payload.decision,
            notes=payload.notes,
            accepted_quantity=payload.accepted_quantity,
        )
        session.commit()
        return result
    except (PermissionDeniedError, ModuleNotEnabledError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ManagerEventError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
