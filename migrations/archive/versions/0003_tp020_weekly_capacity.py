"""TP-020: manually declared weekly availability blocks.

Revision ID: 0003_tp020
Revises: 0002_tp011b
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_tp020"
down_revision = "0002_tp011b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "availability_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        # Original timezone offsets are retained for correct local-week display.
        sa.Column("starts_at", sa.String(40), nullable=False),
        sa.Column("ends_at", sa.String(40), nullable=False),
        sa.Column(
            "work_type_id",
            sa.String(36),
            sa.ForeignKey("work_types.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_availability_blocks_week", "availability_blocks", ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_availability_blocks_week", table_name="availability_blocks")
    op.drop_table("availability_blocks")
