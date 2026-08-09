from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import (
    EventStatus,
    MembershipRole,
    MovementType,
    PayableStatus,
    ProductType,
    PurchaseStatus,
    TransferStatus,
)


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_unit_org_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemModule(Base):
    __tablename__ = "system_modules"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OrganizationModule(Base):
    __tablename__ = "organization_modules"
    __table_args__ = (UniqueConstraint("organization_id", "module_code", name="uq_org_module"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    module_code: Mapped[str] = mapped_column(ForeignKey("system_modules.code"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default=MembershipRole.OPERATOR.value, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccessToken(Base):
    __tablename__ = "access_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserModulePermission(Base):
    __tablename__ = "user_module_permissions"
    __table_args__ = (UniqueConstraint("membership_id", "module_code", name="uq_membership_module"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"), index=True)
    module_code: Mapped[str] = mapped_column(ForeignKey("system_modules.code"), index=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_register: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_configure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("organization_id", "channel", "correlation_id", name="uq_event_channel_correlation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="internal", nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    source_original: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(80), index=True)
    interpretation: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String(40), default=EventStatus.RECEIVED.value, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class EventModuleTarget(Base):
    __tablename__ = "event_module_targets"
    __table_args__ = (UniqueConstraint("event_id", "module_code", name="uq_event_module"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    module_code: Mapped[str] = mapped_column(ForeignKey("system_modules.code"), index=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    approver_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_product_org_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_type: Mapped[str] = mapped_column(String(30), default=ProductType.RAW_MATERIAL.value, nullable=False)
    base_unit: Mapped[str] = mapped_column(String(20), default="kg", nullable=False)
    package_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_recipe_org_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    output_product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    output_quantity_per_batch: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (UniqueConstraint("recipe_id", "product_id", name="uq_recipe_product"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    quantity_per_batch: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    product: Mapped[Product] = relationship(lazy="joined")


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (UniqueConstraint("organization_id", "unit_id", "product_id", name="uq_inventory_balance"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    avg_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), nullable=False)

    @property
    def total_value(self) -> Decimal:
        return Decimal(self.quantity) * Decimal(self.avg_unit_cost)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProductionBatch(Base):
    __tablename__ = "production_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    batch_count: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    output_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_material_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    output_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    destination_unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    dispatch_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    receipt_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=TransferStatus.IN_TRANSIT.value, nullable=False)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("organization_id", "document_number", name="uq_supplier_org_doc"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CostCenter(Base):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_cost_center_org_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id"), index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (UniqueConstraint("organization_id", "supplier_id", "invoice_number", name="uq_purchase_invoice"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    destination_unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=PurchaseStatus.WAITING_APPROVAL.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AccountsPayable(Base):
    __tablename__ = "accounts_payable"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    purchase_id: Mapped[str] = mapped_column(ForeignKey("purchases.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=PayableStatus.OPEN.value, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PurchaseAllocation(Base):
    __tablename__ = "purchase_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    purchase_id: Mapped[str] = mapped_column(ForeignKey("purchases.id"), index=True)
    cost_center_id: Mapped[str] = mapped_column(ForeignKey("cost_centers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
