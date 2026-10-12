"""TP-022B: additive, audited availability exceptions; no reservation changes.

Revision ID: 0012_tp022b
Revises: 0011_tp022a
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_tp022b"
down_revision = "0011_tp022a"
branch_labels = None
depends_on = None

_NEW = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION')"
_OLD = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE')"


def _history_constraint(expr: str) -> None:
    with op.batch_alter_table(
        "history_events",
        recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_history_events_entity_type", type_="check")
        batch.create_check_constraint("ck_history_events_entity_type", expr)


def upgrade() -> None:
    op.create_table(
        "availability_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(36),
                  sa.ForeignKey("recurring_availability_rules.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("original_local_date", sa.Date(), nullable=True),
        sa.Column("starts_at", sa.String(40), nullable=True),
        sa.Column("ends_at", sa.String(40), nullable=True),
        sa.Column("timezone_name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("work_type_id", sa.String(36),
                  sa.ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_availability_exceptions_version"),
        sa.CheckConstraint("action IN ('CANCEL','REPLACE','ADD','UNAVAILABLE')",
                           name="ck_availability_exceptions_action"),
        sa.CheckConstraint("mode IS NULL OR mode IN ('PROTECTED','PREFERRED')",
                           name="ck_availability_exceptions_mode"),
        sa.CheckConstraint("kind IS NULL OR kind IN ('GENERAL','CATEGORIZED')",
                           name="ck_availability_exceptions_kind"),
        sa.UniqueConstraint("owner_id", "rule_id", "original_local_date",
                            name="uq_availability_exception_target"),
    )
    op.create_index("ix_availability_exceptions_owner", "availability_exceptions", ["owner_id"])
    _history_constraint(_NEW)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM availability_exceptions LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: availability exceptions exist")
    if bind.execute(sa.text("SELECT 1 FROM history_events WHERE entity_type = 'AVAILABILITY_EXCEPTION' LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: availability exception audit exists")
    _history_constraint(_OLD)
    op.drop_index("ix_availability_exceptions_owner", table_name="availability_exceptions")
    op.drop_table("availability_exceptions")
