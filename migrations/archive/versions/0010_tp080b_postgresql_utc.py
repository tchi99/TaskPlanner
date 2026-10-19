"""TP-080B: preserve UTC instants across PostgreSQL connections.

Revision ID: 0010_tp080b
Revises: 0009_tp071

Legacy SQLite DateTime values are kept untouched. Existing PostgreSQL
timestamp-without-time-zone values from the original migrations are interpreted
as UTC during the one-time upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_tp080b"
down_revision = "0009_tp071"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("weekly_decisions", "decided_at", False),
    ("resume_points", "updated_at", False),
    ("work_sessions", "started_at", False),
    ("work_sessions", "active_since", True),
    ("work_sessions", "finished_at", True),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, nullable in _COLUMNS:
        op.alter_column(
            table, column,
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, nullable in reversed(_COLUMNS):
        op.alter_column(
            table, column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
