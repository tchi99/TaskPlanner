"""TP-021: optional per-segment protection with parent protection floor.

Revision ID: 0004_tp021
Revises: 0003_tp020
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_tp021"
down_revision = "0003_tp020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_segments") as batch:
        batch.add_column(sa.Column("protection_override", sa.String(32), nullable=True))
        batch.create_check_constraint(
            "ck_task_segments_protection_override",
            "protection_override IS NULL OR protection_override IN ('PROTECTED','REPLANNABLE','FLEXIBLE')",
        )


def downgrade() -> None:
    with op.batch_alter_table("task_segments") as batch:
        batch.drop_constraint("ck_task_segments_protection_override", type_="check")
        batch.drop_column("protection_override")
