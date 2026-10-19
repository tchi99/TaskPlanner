"""TP-025D: extend append-only history for contextual eligibility edits.

Revision ID: 0019_tp025d
Revises: 0018_tp025b
The SQLite table copy preserves all existing audit rows and indexes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_tp025d"
down_revision = "0018_tp025b"
branch_labels = None
depends_on = None

_OLD = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION','TIME_BLOCK')"
_NEW = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION','TIME_BLOCK','ELIGIBILITY_SERIES')"


def _history_constraint(expr: str) -> None:
    # Mirror the tested TP-022A/B migration contract: SQLite rebuilds the
    # CHECK safely while PostgreSQL alters only the named constraint.
    with op.batch_alter_table(
        "history_events",
        recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_history_events_entity_type", type_="check")
        batch.create_check_constraint("ck_history_events_entity_type", expr)


def upgrade() -> None:
    _history_constraint(_NEW)


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM history_events WHERE entity_type = 'ELIGIBILITY_SERIES' LIMIT 1"
    )).first():
        raise RuntimeError("cannot downgrade: eligibility series audit must be retained")
    _history_constraint(_OLD)
