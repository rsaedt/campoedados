from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InboundMedia:
    kind: str
    file_id: str
    mime_type: str | None = None
    filename: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class InboundChannelMessage:
    channel: str
    account_key: str
    external_user_id: str
    external_chat_id: str
    external_id: str
    text: str
    media: InboundMedia | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class DownloadedMedia:
    content: bytes
    mime_type: str
    filename: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class ChannelDispatchResult:
    reply_text: str
    event_id: str | None = None
    status: str | None = None
    unknown_identity: bool = False


class ChannelTransport(Protocol):
    def download_media(self, account_key: str, media: InboundMedia) -> DownloadedMedia:
        ...

    def send_text(self, account_key: str, target: str, text: str) -> None:
        ...
