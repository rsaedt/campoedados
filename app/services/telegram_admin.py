from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.services.auth import Principal
from app.services.channel_accounts import create_channel_account


class TelegramAdminError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramConnectionResult:
    account_id: str
    account_key: str
    bot_id: str
    bot_username: str | None
    display_name: str
    webhook_url: str


def connect_telegram_bot(
    session: Session,
    *,
    principal: Principal,
    account_key: str,
    bot_token: str,
    public_base_url: str,
    display_name: str | None = None,
    client: httpx.Client | None = None,
) -> TelegramConnectionResult:
    key = account_key.strip()
    token = bot_token.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,80}", key):
        raise TelegramAdminError("Identificador do bot deve usar apenas letras, números, _ ou -.")
    if not token:
        raise TelegramAdminError("Token do bot Telegram é obrigatório.")

    owned_client = client is None
    http = client or httpx.Client(timeout=20.0)
    try:
        me_response = http.get(f"https://api.telegram.org/bot{token}/getMe")
        me_response.raise_for_status()
        me = me_response.json()
        if not me.get("ok"):
            raise TelegramAdminError(me.get("description") or "Telegram rejeitou o token informado.")
        bot = me.get("result") or {}
        bot_id = str(bot.get("id") or "")
        if not bot_id:
            raise TelegramAdminError("Telegram não retornou a identidade do bot.")
        username = bot.get("username")
        name = display_name.strip() if display_name and display_name.strip() else (
            f"@{username}" if username else str(bot.get("first_name") or key)
        )

        webhook_secret = secrets.token_urlsafe(32)
        base = public_base_url.rstrip("/")
        webhook_url = f"{base}/v1/channels/webhooks/telegram/{key}"

        account = create_channel_account(
            session,
            principal=principal,
            channel="telegram",
            account_key=key,
            credential=token,
            webhook_secret=webhook_secret,
            display_name=name,
            external_account_id=bot_id,
        )

        webhook_response = http.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": webhook_secret,
                "allowed_updates": ["message", "edited_message"],
                "drop_pending_updates": False,
            },
        )
        webhook_response.raise_for_status()
        webhook = webhook_response.json()
        if not webhook.get("ok"):
            raise TelegramAdminError(webhook.get("description") or "Telegram recusou o webhook.")

        return TelegramConnectionResult(
            account_id=account.id,
            account_key=key,
            bot_id=bot_id,
            bot_username=username,
            display_name=name,
            webhook_url=webhook_url,
        )
    except httpx.HTTPStatusError as exc:
        detail = None
        try:
            detail = exc.response.json().get("description")
        except Exception:
            pass
        raise TelegramAdminError(detail or "Falha de comunicação com a API do Telegram.") from exc
    except httpx.HTTPError as exc:
        raise TelegramAdminError("Não foi possível comunicar com a API do Telegram.") from exc
    finally:
        if owned_client:
            http.close()
