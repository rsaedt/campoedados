from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel import ChannelAccount
from app.services.auth import Principal
from app.services.channel_identity import require_channel_admin


class ChannelAccountError(RuntimeError):
    pass


class ChannelCredentialConfigurationError(ChannelAccountError):
    pass


@dataclass(frozen=True)
class DecryptedChannelCredentials:
    credential: str
    webhook_secret: str


class CredentialCipher:
    def __init__(self, key: str | bytes):
        try:
            self._fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        except Exception as exc:
            raise ChannelCredentialConfigurationError(
                "CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY inválida. Use uma chave Fernet válida."
            ) from exc

    @classmethod
    def from_env(cls) -> "CredentialCipher":
        key = os.getenv("CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY", "").strip()
        if not key:
            raise ChannelCredentialConfigurationError(
                "Credenciais de canal exigem CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY no servidor."
            )
        return cls(key)

    def encrypt(self, value: str) -> str:
        if not value:
            raise ChannelAccountError("Segredo de canal vazio não é permitido.")
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ChannelCredentialConfigurationError(
                "Não foi possível descriptografar a credencial de canal com a chave atual."
            ) from exc


def create_channel_account(
    session: Session,
    *,
    principal: Principal,
    channel: str,
    account_key: str,
    credential: str,
    webhook_secret: str,
    display_name: str | None = None,
    external_account_id: str | None = None,
    cipher: CredentialCipher | None = None,
) -> ChannelAccount:
    require_channel_admin(principal)
    normalized_channel = channel.strip().lower()
    normalized_key = account_key.strip()
    if normalized_channel not in {"telegram"}:
        raise ChannelAccountError(
            "Nesta etapa, contas por cliente são suportadas para Telegram. WhatsApp oficial permanece infraestrutura global."
        )
    if not normalized_key:
        raise ChannelAccountError("account_key é obrigatório.")

    existing = session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == normalized_channel,
            ChannelAccount.account_key == normalized_key,
        )
    )
    if existing is not None:
        raise ChannelAccountError("Já existe uma conta de canal com este account_key.")

    crypto = cipher or CredentialCipher.from_env()
    row = ChannelAccount(
        organization_id=principal.organization_id,
        channel=normalized_channel,
        account_key=normalized_key,
        display_name=display_name,
        external_account_id=external_account_id,
        credential_ciphertext=crypto.encrypt(credential),
        webhook_secret_ciphertext=crypto.encrypt(webhook_secret),
        active=True,
    )
    session.add(row)
    session.flush()
    return row


def list_channel_accounts(session: Session, *, principal: Principal) -> list[ChannelAccount]:
    require_channel_admin(principal)
    return list(
        session.scalars(
            select(ChannelAccount)
            .where(ChannelAccount.organization_id == principal.organization_id)
            .order_by(ChannelAccount.channel, ChannelAccount.account_key)
        )
    )


def load_channel_credentials(
    session: Session,
    *,
    channel: str,
    account_key: str,
    cipher: CredentialCipher | None = None,
) -> tuple[ChannelAccount, DecryptedChannelCredentials]:
    row = session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == channel,
            ChannelAccount.account_key == account_key,
            ChannelAccount.active.is_(True),
        )
    )
    if row is None:
        raise ChannelAccountError(f"Conta de canal '{channel}/{account_key}' não cadastrada ou inativa.")
    crypto = cipher or CredentialCipher.from_env()
    return row, DecryptedChannelCredentials(
        credential=crypto.decrypt(row.credential_ciphertext),
        webhook_secret=crypto.decrypt(row.webhook_secret_ciphertext),
    )
