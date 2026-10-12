"""TP-022R: versioned local bookings and append-only decision events.

Revision ID: 0014_tp022r
Revises: 0013_tp022c
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_tp022r"
down_revision = "0013_tp022c"
branch_labels = None
depends_on = None

_OLD = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION')"
_NEW = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION','TIME_BLOCK')"


def _history_check(expr: str) -> None:
    with op.batch_alter_table(
        "history_events",
        recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_history_events_entity_type", type_="check")
        batch.create_check_constraint("ck_history_events_entity_type", expr)


def upgrade() -> None:
    # Never rebuild the legacy booking table: historical rows are preserved.
    with op.batch_alter_table("confirmed_time_blocks") as batch:
        batch.add_column(sa.Column(
            "status", sa.String(16), nullable=False, server_default="CONFIRMED",
        ))
        batch.add_column(sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1",
        ))
    if op.get_bind().dialect.name != "sqlite":
        with op.batch_alter_table("confirmed_time_blocks") as batch:
            batch.create_check_constraint(
                "ck_confirmed_time_blocks_status",
                "status IN ('CONFIRMED','CANCELLED','SUPERSEDED')",
            )
            batch.create_check_constraint(
                "ck_confirmed_time_blocks_revision", "revision > 0",
            )
    _history_check(_NEW)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(
        "SELECT 1 FROM confirmed_time_blocks WHERE status <> 'CONFIRMED' "
        "OR revision <> 1 LIMIT 1"
    )).first():
        raise RuntimeError("cannot downgrade: booking decisions exist")
    if bind.execute(sa.text(
        "SELECT 1 FROM history_events WHERE entity_type = 'TIME_BLOCK' LIMIT 1"
    )).first():
        raise RuntimeError("cannot downgrade: booking audit exists")
    _history_check(_OLD)
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("confirmed_time_blocks") as batch:
            batch.drop_constraint("ck_confirmed_time_blocks_revision", type_="check")
            batch.drop_constraint("ck_confirmed_time_blocks_status", type_="check")
    if bind.dialect.name == "sqlite":
        # Like TP-022C, preserve historical rows without a table rebuild.
        # A batch copy would revalidate unrelated legacy foreign keys.
        op.execute(sa.text("ALTER TABLE confirmed_time_blocks DROP COLUMN revision"))
        op.execute(sa.text("ALTER TABLE confirmed_time_blocks DROP COLUMN status"))
    else:
        with op.batch_alter_table("confirmed_time_blocks") as batch:
            batch.drop_column("revision")
            batch.drop_column("status")
