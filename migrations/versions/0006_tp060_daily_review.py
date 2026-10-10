"""TP-060: explicitly selected and closed daily reviews.

Revision ID: 0006_tp060
Revises: 0005_tp041
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_tp060"
down_revision = "0005_tp041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_reviews",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("timezone_name", sa.String(100), primary_key=True),
        sa.Column("selected_task_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("followups", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("state IN ('OPEN','CLOSED')",
                           name="ck_daily_reviews_state"),
        sa.CheckConstraint("revision > 0", name="ck_daily_reviews_revision"),
    )
    op.create_index("ix_daily_reviews_timezone_day", "daily_reviews",
                    ["timezone_name", "day"])


def downgrade() -> None:
    op.drop_index("ix_daily_reviews_timezone_day", table_name="daily_reviews")
    op.drop_table("daily_reviews")
