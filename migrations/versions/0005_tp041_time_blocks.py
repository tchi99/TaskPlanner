"""TP-041: accepted local time-block reservations.

Revision ID: 0005_tp041
Revises: 0004_tp021
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_tp041"
down_revision = "0004_tp021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confirmed_time_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("segment_id", sa.String(36),
                  sa.ForeignKey("task_segments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("work_type_id", sa.String(36),
                  sa.ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("starts_at", sa.String(40), nullable=False),
        sa.Column("ends_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("task_id", "segment_id", "starts_at",
                            name="uq_confirmed_time_block_unit_start"),
    )
    op.create_index("ix_confirmed_time_blocks_week", "confirmed_time_blocks",
                    ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_confirmed_time_blocks_week", table_name="confirmed_time_blocks")
    op.drop_table("confirmed_time_blocks")
