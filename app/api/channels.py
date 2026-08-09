from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.channel_dispatch import dispatch_channel_message
from app.services.channels.telegram import (
    TelegramConfigurationError,
    get_telegram_transport,
    parse_telegram_update,
)
from app.services.channels.whatsapp import (
    WhatsAppConfigurationError,
    get_whatsapp_transport,
    parse_whatsapp_messages,
)
from app.services.media_storage import FileSystemMediaStorage, get_media_storage
from app.services.openai_multimodal import MultimodalAI, get_multimodal_ai


router = APIRouter(prefix="/v1/channels/webhooks", tags=["channel-webhooks"])


def whatsapp_transport_factory():
    return get_whatsapp_transport()


def telegram_transport_factory(account_key: str):
    return get_telegram_transport(account_key)


@router.get("/whatsapp")
def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    try:
        transport = whatsapp_transport_factory()
    except WhatsAppConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if mode == "subscribe" and verify_token == transport.config.verify_token and challenge is not None:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Falha na verificação do webhook WhatsApp.")


@router.post("/whatsapp")
async def post_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: Session = Depends(get_db),
    ai: MultimodalAI = Depends(get_multimodal_ai),
    storage: FileSystemMediaStorage = Depends(get_media_storage),
):
    raw = await request.body()
    try:
        transport = whatsapp_transport_factory()
    except WhatsAppConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not transport.verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura WhatsApp inválida.")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload WhatsApp inválido.") from exc

    processed = 0
    for inbound in parse_whatsapp_messages(payload):
        try:
            result = dispatch_channel_message(
                session,
                inbound=inbound,
                transport=transport,
                ai=ai,
                storage=storage,
            )
            session.commit()
            transport.send_text(inbound.account_key, inbound.external_chat_id, result.reply_text)
            processed += 1
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=502, detail=f"Falha ao processar mensagem WhatsApp: {exc}") from exc

    return {"ok": True, "processed": processed}


@router.post("/telegram/{account_key}")
async def post_telegram_webhook(
    account_key: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
    session: Session = Depends(get_db),
    ai: MultimodalAI = Depends(get_multimodal_ai),
    storage: FileSystemMediaStorage = Depends(get_media_storage),
):
    try:
        transport = telegram_transport_factory(account_key)
    except TelegramConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not transport.verify_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Segredo do webhook Telegram inválido.")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload Telegram inválido.") from exc

    inbound = parse_telegram_update(payload, account_key=account_key)
    if inbound is None:
        return {"ok": True, "processed": 0}

    try:
        result = dispatch_channel_message(
            session,
            inbound=inbound,
            transport=transport,
            ai=ai,
            storage=storage,
        )
        session.commit()
        transport.send_text(inbound.account_key, inbound.external_chat_id, result.reply_text)
        return {"ok": True, "processed": 1, "event_id": result.event_id}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=f"Falha ao processar mensagem Telegram: {exc}") from exc
