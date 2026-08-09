from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

import httpx

from app.services.channels.base import DownloadedMedia, InboundChannelMessage, InboundMedia


class WhatsAppConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhatsAppConfig:
    access_token: str
    phone_number_id: str
    app_secret: str
    verify_token: str
    graph_version: str

    @classmethod
    def from_env(cls) -> "WhatsAppConfig":
        access_token = os.getenv("CAMPOEDADOS_WHATSAPP_ACCESS_TOKEN", "")
        phone_number_id = os.getenv("CAMPOEDADOS_WHATSAPP_PHONE_NUMBER_ID", "")
        app_secret = os.getenv("CAMPOEDADOS_WHATSAPP_APP_SECRET", "")
        verify_token = os.getenv("CAMPOEDADOS_WHATSAPP_VERIFY_TOKEN", "")
        graph_version = os.getenv("CAMPOEDADOS_WHATSAPP_GRAPH_VERSION", "")
        missing = [
            name
            for name, value in [
                ("CAMPOEDADOS_WHATSAPP_ACCESS_TOKEN", access_token),
                ("CAMPOEDADOS_WHATSAPP_PHONE_NUMBER_ID", phone_number_id),
                ("CAMPOEDADOS_WHATSAPP_APP_SECRET", app_secret),
                ("CAMPOEDADOS_WHATSAPP_VERIFY_TOKEN", verify_token),
                ("CAMPOEDADOS_WHATSAPP_GRAPH_VERSION", graph_version),
            ]
            if not value
        ]
        if missing:
            raise WhatsAppConfigurationError("Configuração WhatsApp ausente: " + ", ".join(missing))
        return cls(
            access_token=access_token,
            phone_number_id=phone_number_id,
            app_secret=app_secret,
            verify_token=verify_token,
            graph_version=graph_version,
        )


class WhatsAppTransport:
    def __init__(self, config: WhatsAppConfig, *, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=30.0)

    def verify_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = hmac.new(
            self.config.app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        supplied = signature_header.split("=", 1)[1]
        return hmac.compare_digest(expected, supplied)

    def download_media(self, account_key: str, media: InboundMedia) -> DownloadedMedia:
        if account_key != self.config.phone_number_id:
            raise WhatsAppConfigurationError("phone_number_id recebido não corresponde à conta configurada.")
        headers = {"Authorization": f"Bearer {self.config.access_token}"}
        meta_url = f"https://graph.facebook.com/{self.config.graph_version}/{media.file_id}"
        response = self.client.get(
            meta_url,
            params={"phone_number_id": account_key},
            headers=headers,
        )
        response.raise_for_status()
        meta = response.json()
        media_url = meta["url"]
        binary = self.client.get(media_url, headers=headers)
        binary.raise_for_status()
        mime_type = (
            meta.get("mime_type")
            or binary.headers.get("content-type")
            or media.mime_type
            or "application/octet-stream"
        ).split(";", 1)[0].lower()
        return DownloadedMedia(
            content=binary.content,
            mime_type=mime_type,
            filename=media.filename,
            sha256=meta.get("sha256") or media.sha256,
        )

    def send_text(self, account_key: str, target: str, text: str) -> None:
        if account_key != self.config.phone_number_id:
            raise WhatsAppConfigurationError("phone_number_id recebido não corresponde à conta configurada.")
        url = f"https://graph.facebook.com/{self.config.graph_version}/{account_key}/messages"
        response = self.client.post(
            url,
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": target,
                "type": "text",
                "text": {"body": text},
            },
        )
        response.raise_for_status()


def parse_whatsapp_messages(payload: dict) -> list[InboundChannelMessage]:
    result: list[InboundChannelMessage] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            account_key = str(metadata.get("phone_number_id") or "")
            contacts = {
                str(row.get("wa_id")): ((row.get("profile") or {}).get("name"))
                for row in (value.get("contacts") or [])
                if row.get("wa_id")
            }
            for message in value.get("messages") or []:
                sender = str(message.get("from") or "")
                message_id = str(message.get("id") or "")
                if not sender or not message_id or not account_key:
                    continue
                msg_type = str(message.get("type") or "")
                text = ""
                media = None
                if msg_type == "text":
                    text = str((message.get("text") or {}).get("body") or "")
                elif msg_type in {"image", "audio", "document"}:
                    part = message.get(msg_type) or {}
                    text = str(part.get("caption") or "")
                    media_id = part.get("id")
                    if media_id:
                        media = InboundMedia(
                            kind="audio" if msg_type == "audio" else msg_type,
                            file_id=str(media_id),
                            mime_type=part.get("mime_type"),
                            filename=part.get("filename"),
                            sha256=part.get("sha256"),
                        )
                else:
                    text = f"[mensagem {msg_type or 'não suportada'}]"
                result.append(
                    InboundChannelMessage(
                        channel="whatsapp",
                        account_key=account_key,
                        external_user_id=sender,
                        external_chat_id=sender,
                        external_id=message_id,
                        text=text,
                        media=media,
                        display_name=contacts.get(sender),
                    )
                )
    return result


def get_whatsapp_transport() -> WhatsAppTransport:
    return WhatsAppTransport(WhatsAppConfig.from_env())
