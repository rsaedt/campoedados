from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.domain import new_id, utcnow


class ConsumptionRecord(Base):
    """Uso real de um produto do estoque de uma fazenda.

    O estoque continua pertencendo à unidade/fazenda. Este registro explica
    para que o produto saiu, sem criar depósitos ou transferências internas.
    """

    __tablename__ = "consumption_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True, unique=True)
    inventory_movement_id: Mapped[str] = mapped_column(
        ForeignKey("inventory_movements.id"), index=True, unique=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose_label: Mapped[str] = mapped_column(String(120), nullable=False)
    context_label: Mapped[str | None] = mapped_column(String(180))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
