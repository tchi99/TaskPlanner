"""TP-070: confirmed task resume markers, independent of work sessions.

Revision ID: 0008_tp070
Revises: 0007_tp061
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_tp070"
down_revision = "0007_tp061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_points",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_resume_points_revision"),
        sa.CheckConstraint(
            "action_type IN ('CLARIFY_TASK','WORK_ON_TASK','WORK_ON_SEGMENT','REVIEW_COMPLETION')",
            name="ck_resume_points_action_type",
        ),
        sa.CheckConstraint("text IS NULL OR length(text) BETWEEN 1 AND 240",
                           name="ck_resume_points_text_length"),
    )


def downgrade() -> None:
    op.drop_table("resume_points")
