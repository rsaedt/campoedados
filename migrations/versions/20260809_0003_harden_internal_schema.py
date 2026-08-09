"""Protege metadados internos e remove índice duplicado.

Revision ID: 20260809_0003
Revises: 20260809_0002
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0003"
down_revision = "20260809_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A tabela de controle do Alembic também está no schema public do Supabase.
    # Ela não é dado de aplicação e nunca deve ficar acessível pela Data API.
    op.execute(sa.text('ALTER TABLE "alembic_version" ENABLE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON TABLE public.alembic_version FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON TABLE public.alembic_version FROM authenticated;
                END IF;
            END $$;
            """
        )
    )

    # token_hash já possui a restrição/índice único uq_access_tokens_token_hash.
    # O index=True do modelo gerou um segundo índice único idêntico e desnecessário.
    op.drop_index("ix_access_tokens_token_hash", table_name="access_tokens")


def downgrade() -> None:
    op.create_index(
        "ix_access_tokens_token_hash",
        "access_tokens",
        ["token_hash"],
        unique=True,
    )
    op.execute(sa.text('ALTER TABLE "alembic_version" DISABLE ROW LEVEL SECURITY'))
