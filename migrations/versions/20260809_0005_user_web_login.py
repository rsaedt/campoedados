"""Adiciona credenciais de login do usuário.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0005"
down_revision = "20260809_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("login_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("login_name", name="uq_user_credentials_login_name"),
    )
    op.create_index("ix_user_credentials_login_name", "user_credentials", ["login_name"], unique=True)
    op.execute(sa.text('ALTER TABLE "user_credentials" ENABLE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON TABLE public.user_credentials FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON TABLE public.user_credentials FROM authenticated;
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_user_credentials_login_name", table_name="user_credentials")
    op.drop_table("user_credentials")
