from __future__ import annotations

import hmac
from dataclasses import dataclass

import httpx

from app.core.database import SessionLocal
from app.services.channel_accounts import ChannelAccountError, load_channel_credentials
from app.services.channels.base import DownloadedMedia, InboundChannelMessage, InboundMedia


class TelegramConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    secret_token: str

    @classmethod
    def for_account(cls, account_key: str) -> "TelegramBotConfig":
        try:
            with SessionLocal() as session:
                _, credentials = load_channel_credentials(
                    session,
                    channel="telegram",
                    account_key=account_key,
                )
                return cls(
                    token=credentials.credential,
                    secret_token=credentials.webhook_secret,
                )
        except ChannelAccountError as exc:
            raise TelegramConfigurationError(str(exc)) from exc


class TelegramTransport:
    def __init__(self, account_key: str, config: TelegramBotConfig, *, client: httpx.Client | None = None):
        self.account_key = account_key
        self.config = config
        self.client = client or httpx.Client(timeout=30.0)

    def verify_secret(self, supplied: str | None) -> bool:
        return bool(supplied) and hmac.compare_digest(self.config.secret_token, supplied)

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.token}/{method}"

    def download_media(self, account_key: str, media: InboundMedia) -> DownloadedMedia:
        if account_key != self.account_key:
            raise TelegramConfigurationError("Conta Telegram divergente.")
        response = self.client.get(self._api("getFile"), params={"file_id": media.file_id})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("description") or "Telegram getFile falhou.")
        file_path = (body.get("result") or {}).get("file_path")
        if not file_path:
            raise RuntimeError("Telegram não retornou file_path.")
        binary = self.client.get(f"https://api.telegram.org/file/bot{self.config.token}/{file_path}")
        binary.raise_for_status()
        mime_type = (
            media.mime_type
            or binary.headers.get("content-type")
            or "application/octet-stream"
        ).split(";", 1)[0].lower()
        filename = media.filename or file_path.rsplit("/", 1)[-1]
        return DownloadedMedia(content=binary.content, mime_type=mime_type, filename=filename)

    def send_text(self, account_key: str, target: str, text: str) -> None:
        if account_key != self.account_key:
            raise TelegramConfigurationError("Conta Telegram divergente.")
        response = self.client.post(
            self._api("sendMessage"),
            json={"chat_id": target, "text": text},
        )
        response.raise_for_status()


def parse_telegram_update(payload: dict, *, account_key: str) -> InboundChannelMessage | None:
    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return None
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    external_user_id = str(sender.get("id") or "")
    external_chat_id = str(chat.get("id") or "")
    update_id = payload.get("update_id")
    message_id = message.get("message_id")
    if not external_user_id or not external_chat_id:
        return None
    external_id = f"{account_key}:{update_id if update_id is not None else message_id}"
    text = str(message.get("text") or message.get("caption") or "")
    media = None

    if message.get("voice"):
        row = message["voice"]
        media = InboundMedia(
            kind="audio",
            file_id=str(row["file_id"]),
            mime_type=row.get("mime_type") or "audio/ogg",
        )
    elif message.get("audio"):
        row = message["audio"]
        media = InboundMedia(
            kind="audio",
            file_id=str(row["file_id"]),
            mime_type=row.get("mime_type"),
            filename=row.get("file_name"),
        )
    elif message.get("photo"):
        row = message["photo"][-1]
        media = InboundMedia(kind="image", file_id=str(row["file_id"]), mime_type="image/jpeg")
    elif message.get("document"):
        row = message["document"]
        media = InboundMedia(
            kind="document",
            file_id=str(row["file_id"]),
            mime_type=row.get("mime_type"),
            filename=row.get("file_name"),
        )

    display_name = " ".join(
        part for part in [str(sender.get("first_name") or ""), str(sender.get("last_name") or "")] if part
    ).strip() or None

    return InboundChannelMessage(
        channel="telegram",
        account_key=account_key,
        external_user_id=external_user_id,
        external_chat_id=external_chat_id,
        external_id=external_id,
        text=text,
        media=media,
        display_name=display_name,
    )


def get_telegram_transport(account_key: str) -> TelegramTransport:
    return TelegramTransport(account_key, TelegramBotConfig.for_account(account_key))
