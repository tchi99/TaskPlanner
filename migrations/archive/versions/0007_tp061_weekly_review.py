"""TP-061: local weekly decisions with explicit revision.

Revision ID: 0007_tp061
Revises: 0006_tp060
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_tp061"
down_revision = "0006_tp060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_decisions",
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column("timezone_name", sa.String(100), primary_key=True),
        sa.Column("subject_kind", sa.String(16), primary_key=True),
        sa.Column("subject_id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("review_on", sa.Date(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("subject_kind IN ('TASK','PROJECT')",
                           name="ck_weekly_decisions_subject"),
        sa.CheckConstraint("action IN ('RECIRCULATE','POSTPONE','REVIEW_LATER','DELEGATE','ABANDON')",
                           name="ck_weekly_decisions_action"),
        sa.CheckConstraint("revision > 0", name="ck_weekly_decisions_revision"),
    )


def downgrade() -> None:
    op.drop_table("weekly_decisions")
