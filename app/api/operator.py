from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.schemas.operator import OperatorMessageRequest, OperatorMessageResponse
from app.services.auth import Principal
from app.services.modules import ModuleNotEnabledError
from app.services.operator import InvalidUnitError, handle_operator_message
from app.services.permissions import PermissionDeniedError


router = APIRouter(prefix="/v1/operator", tags=["operator"])


@router.post("/messages", response_model=OperatorMessageResponse)
def post_operator_message(
    payload: OperatorMessageRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        result = handle_operator_message(session, principal=principal, request=payload)
        session.commit()
        return result
    except (PermissionDeniedError, ModuleNotEnabledError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidUnitError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
