"""Schema inicial Campo e Dados 0.6.0.

Revision ID: 20260809_0001
Revises:
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0001"
down_revision = None
branch_labels = None
depends_on = None


def _ix(table: str, column: str, *, unique: bool = False) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    op.create_table(
        "system_modules",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_unit_org_code"),
    )
    _ix("units", "organization_id")

    op.create_table(
        "organization_modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("module_code", sa.String(40), sa.ForeignKey("system_modules.code"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "module_code", name="uq_org_module"),
    )
    _ix("organization_modules", "organization_id")
    _ix("organization_modules", "module_code")

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )
    _ix("memberships", "organization_id")
    _ix("memberships", "user_id")

    op.create_table(
        "access_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("membership_id", sa.String(36), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_access_tokens_token_hash"),
    )
    _ix("access_tokens", "membership_id")
    _ix("access_tokens", "token_hash", unique=True)

    op.create_table(
        "user_module_permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("membership_id", sa.String(36), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("module_code", sa.String(40), sa.ForeignKey("system_modules.code"), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False),
        sa.Column("can_register", sa.Boolean(), nullable=False),
        sa.Column("can_approve", sa.Boolean(), nullable=False),
        sa.Column("can_configure", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("membership_id", "module_code", name="uq_membership_module"),
    )
    _ix("user_module_permissions", "membership_id")
    _ix("user_module_permissions", "module_code")

    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_original", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=True),
        sa.Column("interpretation", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(80), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "channel", "correlation_id", name="uq_event_channel_correlation"),
    )
    for col in ("organization_id", "unit_id", "actor_user_id", "event_type", "correlation_id"):
        _ix("events", col)

    op.create_table(
        "event_module_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("module_code", sa.String(40), sa.ForeignKey("system_modules.code"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("event_id", "module_code", name="uq_event_module"),
    )
    _ix("event_module_targets", "event_id")
    _ix("event_module_targets", "module_code")

    op.create_table(
        "event_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(120), nullable=True),
        sa.Column("storage_ref", sa.String(500), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("extracted_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("event_documents", "event_id")
    _ix("event_documents", "sha256")

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("module_code", sa.String(40), sa.ForeignKey("system_modules.code"), nullable=True),
        sa.Column("approver_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("approvals", "event_id")
    _ix("approvals", "module_code")
    _ix("approvals", "approver_user_id")

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("audit_entries", "organization_id")
    _ix("audit_entries", "event_id")
    _ix("audit_entries", "actor_user_id")

    op.create_table(
        "products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("product_type", sa.String(30), nullable=False),
        sa.Column("base_unit", sa.String(20), nullable=False),
        sa.Column("package_weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_product_org_code"),
    )
    _ix("products", "organization_id")

    op.create_table(
        "recipes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("output_product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("output_quantity_per_batch", sa.Numeric(18, 4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_recipe_org_name"),
    )
    _ix("recipes", "organization_id")
    _ix("recipes", "output_product_id")

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), sa.ForeignKey("recipes.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity_per_batch", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("recipe_id", "product_id", name="uq_recipe_product"),
    )
    _ix("recipe_ingredients", "recipe_id")
    _ix("recipe_ingredients", "product_id")

    op.create_table(
        "inventory_balances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("avg_unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.UniqueConstraint("organization_id", "unit_id", "product_id", name="uq_inventory_balance"),
    )
    _ix("inventory_balances", "organization_id")
    _ix("inventory_balances", "unit_id")
    _ix("inventory_balances", "product_id")

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("movement_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "unit_id", "product_id", "event_id", "reference_id"):
        _ix("inventory_movements", col)

    op.create_table(
        "production_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("recipe_id", sa.String(36), sa.ForeignKey("recipes.id"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("batch_count", sa.Numeric(18, 4), nullable=False),
        sa.Column("output_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_material_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("output_unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "unit_id", "recipe_id", "event_id"):
        _ix("production_batches", col)

    op.create_table(
        "transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source_unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("destination_unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("dispatch_event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("receipt_event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("declared_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("declared_unit", sa.String(20), nullable=True),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("divergence_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "source_unit_id", "destination_unit_id", "product_id", "dispatch_event_id", "receipt_event_id"):
        _ix("transfers", col)

    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("document_number", sa.String(30), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "document_number", name="uq_supplier_org_doc"),
    )
    _ix("suppliers", "organization_id")

    op.create_table(
        "cost_centers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_cost_center_org_code"),
    )
    _ix("cost_centers", "organization_id")
    _ix("cost_centers", "unit_id")

    op.create_table(
        "purchases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.String(36), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("destination_unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("invoice_number", sa.String(80), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "supplier_id", "invoice_number", name="uq_purchase_invoice"),
    )
    for col in ("organization_id", "supplier_id", "destination_unit_id", "event_id"):
        _ix("purchases", col)

    op.create_table(
        "accounts_payable",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_id", sa.String(36), sa.ForeignKey("purchases.id"), nullable=False),
        sa.Column("supplier_id", sa.String(36), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    _ix("accounts_payable", "organization_id")
    _ix("accounts_payable", "purchase_id")
    _ix("accounts_payable", "supplier_id")

    op.create_table(
        "purchase_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purchase_id", sa.String(36), sa.ForeignKey("purchases.id"), nullable=False),
        sa.Column("cost_center_id", sa.String(36), sa.ForeignKey("cost_centers.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
    )
    _ix("purchase_allocations", "purchase_id")
    _ix("purchase_allocations", "cost_center_id")

    op.create_table(
        "channel_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("membership_id", sa.String(36), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("default_unit_id", sa.String(36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("account_key", sa.String(120), nullable=False),
        sa.Column("external_user_id", sa.String(180), nullable=False),
        sa.Column("external_chat_id", sa.String(180), nullable=True),
        sa.Column("display_name", sa.String(180), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel", "account_key", "external_user_id", name="uq_channel_identity_external"),
    )
    for col in ("membership_id", "default_unit_id", "channel", "account_key", "external_user_id"):
        _ix("channel_identities", col)

    # Catálogo compartilhado; habilitação por cliente continua em organization_modules.
    op.bulk_insert(
        sa.table(
            "system_modules",
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("active", sa.Boolean()),
        ),
        [
            {"code": "livestock", "name": "Pecuária", "active": True},
            {"code": "feed_mill", "name": "Fábrica de Ração", "active": True},
            {"code": "finance", "name": "Financeiro", "active": True},
        ],
    )


def downgrade() -> None:
    for table in [
        "channel_identities",
        "purchase_allocations",
        "accounts_payable",
        "purchases",
        "cost_centers",
        "suppliers",
        "transfers",
        "production_batches",
        "inventory_movements",
        "inventory_balances",
        "recipe_ingredients",
        "recipes",
        "products",
        "audit_entries",
        "approvals",
        "event_documents",
        "event_module_targets",
        "events",
        "user_module_permissions",
        "access_tokens",
        "memberships",
        "organization_modules",
        "units",
        "users",
        "system_modules",
        "organizations",
    ]:
        op.drop_table(table)
