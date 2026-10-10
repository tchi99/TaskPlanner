"""TP-071: explicit work sessions (revision after 0008_tp070)."""
from alembic import op
import sqlalchemy as sa

revision = "0009_tp071"
down_revision = "0008_tp070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36),
                  sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        # Deliberate historical identifier: removed segments must remain addressable.
        sa.Column("segment_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("active_since", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("active_seconds", sa.Integer(), nullable=False),
        sa.Column("interruptions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("work_type_id", sa.String(36), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("planned_minutes", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE','PAUSED','FINISHED')",
                           name="ck_work_sessions_status"),
        sa.CheckConstraint("active_seconds >= 0 AND interruptions >= 0 AND revision > 0",
                           name="ck_work_sessions_counters"),
        sa.CheckConstraint("estimated_minutes IS NULL OR estimated_minutes > 0",
                           name="ck_work_sessions_estimate"),
        sa.CheckConstraint("planned_minutes IS NULL OR planned_minutes > 0",
                           name="ck_work_sessions_plan"),
        sa.CheckConstraint("(status = 'ACTIVE' AND active_since IS NOT NULL AND finished_at IS NULL) OR "
                           "(status = 'PAUSED' AND active_since IS NULL AND finished_at IS NULL) OR "
                           "(status = 'FINISHED' AND active_since IS NULL AND finished_at IS NOT NULL)",
                           name="ck_work_sessions_lifecycle"),
    )
    op.create_index("ix_work_sessions_task_started", "work_sessions",
                    ["task_id", "started_at"])
    op.create_index("uq_work_sessions_single_active", "work_sessions", ["status"],
                    unique=True, sqlite_where=sa.text("status = 'ACTIVE'"))


def downgrade() -> None:
    op.drop_index("uq_work_sessions_single_active", table_name="work_sessions")
    op.drop_index("ix_work_sessions_task_started", table_name="work_sessions")
    op.drop_table("work_sessions")
