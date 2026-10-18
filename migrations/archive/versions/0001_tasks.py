"""create tasks table

Revision ID: 0001_tasks
Revises:
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_tasks"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("protection", sa.String(length=32), nullable=False),
        sa.Column("work_type_id", sa.String(length=36), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_tasks_status_created_at",
        "tasks",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_status_created_at", table_name="tasks")
    op.drop_table("tasks")
