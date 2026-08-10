"""Adiciona registro analítico de consumo por fazenda.

Revision ID: 20260809_0006
Revises: 20260809_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0006"
down_revision = "20260809_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consumption_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("unit_id", sa.String(length=36), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("event_id", sa.String(length=36), sa.ForeignKey("events.id"), nullable=False, unique=True),
        sa.Column(
            "inventory_movement_id",
            sa.String(length=36),
            sa.ForeignKey("inventory_movements.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("purpose_code", sa.String(length=40), nullable=False),
        sa.Column("purpose_label", sa.String(length=120), nullable=False),
        sa.Column("context_label", sa.String(length=180), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_consumption_records_organization_id", "consumption_records", ["organization_id"])
    op.create_index("ix_consumption_records_unit_id", "consumption_records", ["unit_id"])
    op.create_index("ix_consumption_records_product_id", "consumption_records", ["product_id"])
    op.create_index("ix_consumption_records_event_id", "consumption_records", ["event_id"])
    op.create_index(
        "ix_consumption_records_inventory_movement_id",
        "consumption_records",
        ["inventory_movement_id"],
    )
    op.execute("ALTER TABLE consumption_records ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("consumption_records")
