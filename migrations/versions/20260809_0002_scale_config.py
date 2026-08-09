"""Configuração escalável e contas de canal.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0002"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


APP_TABLES = [
    "organizations",
    "system_modules",
    "users",
    "units",
    "organization_modules",
    "memberships",
    "access_tokens",
    "user_module_permissions",
    "events",
    "event_module_targets",
    "event_documents",
    "approvals",
    "audit_entries",
    "products",
    "recipes",
    "recipe_ingredients",
    "inventory_balances",
    "inventory_movements",
    "production_batches",
    "transfers",
    "suppliers",
    "cost_centers",
    "purchases",
    "accounts_payable",
    "purchase_allocations",
    "channel_identities",
    "channel_accounts",
]


def upgrade() -> None:
    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("account_key", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(180), nullable=True),
        sa.Column("external_account_id", sa.String(180), nullable=True),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column("webhook_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel", "account_key", name="uq_channel_account_key"),
    )
    op.create_index("ix_channel_accounts_organization_id", "channel_accounts", ["organization_id"])
    op.create_index("ix_channel_accounts_channel", "channel_accounts", ["channel"])
    op.create_index("ix_channel_accounts_account_key", "channel_accounts", ["account_key"])
    op.create_index("ix_channel_accounts_external_account_id", "channel_accounts", ["external_account_id"])

    # O backend acessa Postgres diretamente. As tabelas do produto não devem ficar abertas
    # por acidente pela Data API do Supabase. RLS sem políticas fecha o acesso público;
    # o papel proprietário/server-side continua responsável pela aplicação.
    for table in APP_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))

    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                table_name text;
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    FOREACH table_name IN ARRAY ARRAY[
                        'organizations','system_modules','users','units','organization_modules',
                        'memberships','access_tokens','user_module_permissions','events',
                        'event_module_targets','event_documents','approvals','audit_entries',
                        'products','recipes','recipe_ingredients','inventory_balances',
                        'inventory_movements','production_batches','transfers','suppliers',
                        'cost_centers','purchases','accounts_payable','purchase_allocations',
                        'channel_identities','channel_accounts'
                    ] LOOP
                        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon', table_name);
                    END LOOP;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    FOREACH table_name IN ARRAY ARRAY[
                        'organizations','system_modules','users','units','organization_modules',
                        'memberships','access_tokens','user_module_permissions','events',
                        'event_module_targets','event_documents','approvals','audit_entries',
                        'products','recipes','recipe_ingredients','inventory_balances',
                        'inventory_movements','production_batches','transfers','suppliers',
                        'cost_centers','purchases','accounts_payable','purchase_allocations',
                        'channel_identities','channel_accounts'
                    ] LOOP
                        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM authenticated', table_name);
                    END LOOP;
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    for table in APP_TABLES:
        if table != "channel_accounts":
            op.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
    op.drop_index("ix_channel_accounts_external_account_id", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_account_key", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_channel", table_name="channel_accounts")
    op.drop_index("ix_channel_accounts_organization_id", table_name="channel_accounts")
    op.drop_table("channel_accounts")
