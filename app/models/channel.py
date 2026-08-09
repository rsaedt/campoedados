from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.domain import new_id, utcnow


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
