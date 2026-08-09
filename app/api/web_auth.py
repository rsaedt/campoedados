from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.database import get_db
from app.services.audit import record_audit
from app.services.auth import AuthenticationError, Principal
from app.services.web_auth import (
    FirstAccessError,
    SESSION_COOKIE,
    SESSION_HOURS,
    configure_first_access,
    login_with_password,
    revoke_web_session,
)


router = APIRouter(prefix="/v1/auth", tags=["web-auth"])


class LoginRequest(BaseModel):
    login_name: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    organization_slug: str | None = Field(default=None, max_length=80)


class FirstAccessRequest(BaseModel):
    organization_slug: str = Field(min_length=2, max_length=80)
    admin_name: str = Field(min_length=2, max_length=160)
    login_name: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=200)


def _session_payload(principal: Principal) -> dict:
    return {
        "authenticated": True,
        "user_id": principal.user_id,
        "display_name": principal.user.display_name,
        "role": principal.membership.role,
        "organization_id": principal.organization_id,
        "organization": principal.organization.name,
        "organization_slug": principal.organization.slug,
    }


def _set_session_cookie(response: Response, raw_session: str) -> None:
    environment = os.getenv("CAMPOEDADOS_ENV", "development").strip().lower()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_session,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=environment in {"staging", "production"},
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_db),
):
    try:
        result = login_with_password(
            session,
            login_name=payload.login_name,
            password=payload.password,
            organization_slug=payload.organization_slug,
        )
        record_audit(
            session,
            organization_id=result.principal.organization_id,
            actor_user_id=result.principal.user_id,
            action="web_login",
            details={"membership_id": result.principal.membership.id},
        )
        session.commit()
        _set_session_cookie(response, result.raw_session)
        return _session_payload(result.principal)
    except AuthenticationError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/first-access")
def first_access(
    payload: FirstAccessRequest,
    response: Response,
    session: Session = Depends(get_db),
):
    try:
        result = configure_first_access(
            session,
            organization_slug=payload.organization_slug,
            admin_name=payload.admin_name,
            login_name=payload.login_name,
            password=payload.password,
        )
        record_audit(
            session,
            organization_id=result.principal.organization_id,
            actor_user_id=result.principal.user_id,
            action="web_first_access_configured",
            details={
                "membership_id": result.principal.membership.id,
                "login_name": payload.login_name.strip().casefold(),
            },
        )
        session.commit()
        _set_session_cookie(response, result.raw_session)
        return _session_payload(result.principal)
    except (FirstAccessError, AuthenticationError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/session")
def current_session(principal: Principal = Depends(get_current_principal)):
    return _session_payload(principal)


@router.post("/logout")
def logout(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
):
    revoke_web_session(session, token_id=principal.token_id)
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
