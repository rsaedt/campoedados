from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.domain import new_id, utcnow


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint("channel", "account_key", name="uq_channel_account_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    account_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(180))
    external_account_id: Mapped[str | None] = mapped_column(String(180), index=True)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "account_key",
            "external_user_id",
            name="uq_channel_identity_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    default_unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    account_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    external_chat_id: Mapped[str | None] = mapped_column(String(180))
    display_name: Mapped[str | None] = mapped_column(String(180))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ChannelContactRequest(Base):
    """Contato que falou com um canal válido, mas ainda não foi vinculado a um usuário."""

    __tablename__ = "channel_contact_requests"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "account_key",
            "external_user_id",
            name="uq_channel_contact_request_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    account_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    external_chat_id: Mapped[str | None] = mapped_column(String(180))
    display_name: Mapped[str | None] = mapped_column(String(180))
    last_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    linked_identity_id: Mapped[str | None] = mapped_column(ForeignKey("channel_identities.id"), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
