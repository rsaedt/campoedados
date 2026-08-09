from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.models.domain import Unit
from app.schemas.channels import ChannelIdentityCreate, ChannelIdentityResult
from app.services.auth import Principal
from app.services.channel_identity import (
    ChannelIdentityAdminError,
    create_channel_identity,
    list_channel_identities,
)


router = APIRouter(prefix="/v1/admin/channel-identities", tags=["admin-channels"])


def _result(row, unit) -> ChannelIdentityResult:
    return ChannelIdentityResult(
        id=row.id,
        membership_id=row.membership_id,
        default_unit_code=unit.code,
        channel=row.channel,
        account_key=row.account_key,
        external_user_id=row.external_user_id,
        external_chat_id=row.external_chat_id,
        display_name=row.display_name,
        active=row.active,
    )


@router.post("", response_model=ChannelIdentityResult, status_code=status.HTTP_201_CREATED)
def post_channel_identity(
    payload: ChannelIdentityCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        row = create_channel_identity(session, principal=principal, payload=payload)
        unit = session.get(Unit, row.default_unit_id)
        session.commit()
        return _result(row, unit)
    except ChannelIdentityAdminError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("", response_model=list[ChannelIdentityResult])
def get_channel_identities(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        return [_result(row, unit) for row, unit in list_channel_identities(session, principal=principal)]
    except ChannelIdentityAdminError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
