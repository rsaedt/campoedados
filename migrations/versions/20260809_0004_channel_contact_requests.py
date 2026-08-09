"""Adiciona contatos de canal aguardando vínculo.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260809_0004"
down_revision = "20260809_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_contact_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("account_key", sa.String(length=120), nullable=False),
        sa.Column("external_user_id", sa.String(length=180), nullable=False),
        sa.Column("external_chat_id", sa.String(length=180), nullable=True),
        sa.Column("display_name", sa.String(length=180), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("linked_identity_id", sa.String(length=36), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["linked_identity_id"], ["channel_identities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel", "account_key", "external_user_id",
            name="uq_channel_contact_request_external",
        ),
    )
    for column in (
        "organization_id", "channel", "account_key", "external_user_id",
        "status", "linked_identity_id",
    ):
        op.create_index(
            f"ix_channel_contact_requests_{column}",
            "channel_contact_requests",
            [column],
            unique=False,
        )

    op.execute(sa.text('ALTER TABLE "channel_contact_requests" ENABLE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON TABLE public.channel_contact_requests FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON TABLE public.channel_contact_requests FROM authenticated;
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_table("channel_contact_requests")
