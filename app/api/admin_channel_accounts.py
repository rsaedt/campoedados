from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.schemas.channel_accounts import ChannelAccountCreate, ChannelAccountResult
from app.services.auth import Principal
from app.services.channel_accounts import ChannelAccountError, create_channel_account, list_channel_accounts
from app.services.channel_identity import ChannelIdentityAdminError


router = APIRouter(prefix="/v1/admin/channel-accounts", tags=["admin-channel-accounts"])


def _result(row) -> ChannelAccountResult:
    return ChannelAccountResult(
        id=row.id,
        organization_id=row.organization_id,
        channel=row.channel,
        account_key=row.account_key,
        display_name=row.display_name,
        external_account_id=row.external_account_id,
        active=row.active,
        credential_configured=bool(row.credential_ciphertext and row.webhook_secret_ciphertext),
    )


@router.post("", response_model=ChannelAccountResult, status_code=status.HTTP_201_CREATED)
def post_channel_account(
    payload: ChannelAccountCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        row = create_channel_account(
            session,
            principal=principal,
            channel=payload.channel,
            account_key=payload.account_key,
            credential=payload.credential,
            webhook_secret=payload.webhook_secret,
            display_name=payload.display_name,
            external_account_id=payload.external_account_id,
        )
        session.commit()
        return _result(row)
    except ChannelIdentityAdminError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChannelAccountError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[ChannelAccountResult])
def get_channel_accounts(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    try:
        return [_result(row) for row in list_channel_accounts(session, principal=principal)]
    except ChannelIdentityAdminError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ChannelAccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
