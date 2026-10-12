"""TP-022A: additive recurring availability with append-only civil revisions.

Revision ID: 0011_tp022a
Revises: 0010_tp080b
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_tp022a"
down_revision = "0010_tp080b"
branch_labels = None
depends_on = None

_OLD = "entity_type IN ('TASK','SEGMENT')"
_NEW = "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE')"


def _history_constraint(expr: str) -> None:
    # SQLite requires a table copy for CHECK replacement. Alembic batch mode
    # preserves legacy rows and indexes; PG changes only the named constraint.
    with op.batch_alter_table(
        "history_events",
        recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_history_events_entity_type", type_="check")
        batch.create_check_constraint("ck_history_events_entity_type", expr)


def upgrade() -> None:
    op.create_table(
        "recurring_availability_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_recurring_rules_version"),
    )
    op.create_index("ix_recurring_rules_owner", "recurring_availability_rules", ["owner_id"])
    op.create_table(
        "recurring_availability_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_id", sa.String(36),
                  sa.ForeignKey("recurring_availability_rules.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("timezone_name", sa.String(100), nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=False),
        sa.Column("starts_at_local", sa.String(5), nullable=False),
        sa.Column("ends_at_local", sa.String(5), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("work_type_id", sa.String(36),
                  sa.ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("start_fold", sa.Integer(), nullable=True),
        sa.Column("end_fold", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_id", "number", name="uq_recurring_revision_number"),
        sa.UniqueConstraint("rule_id", "effective_from", name="uq_recurring_revision_effective"),
        sa.CheckConstraint("number > 0", name="ck_recurring_revisions_number"),
        sa.CheckConstraint("kind IN ('GENERAL','CATEGORIZED')", name="ck_recurring_revisions_kind"),
        sa.CheckConstraint("mode IS NULL OR mode IN ('PROTECTED','PREFERRED')",
                           name="ck_recurring_revisions_mode"),
        sa.CheckConstraint("start_fold IS NULL OR start_fold IN (0,1)",
                           name="ck_recurring_revisions_start_fold"),
        sa.CheckConstraint("end_fold IS NULL OR end_fold IN (0,1)",
                           name="ck_recurring_revisions_end_fold"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_from",
                           name="ck_recurring_revisions_range"),
    )
    _history_constraint(_NEW)


def downgrade() -> None:
    # Only permitted when no recurring-rule history remains; never silently
    # delete user availability declarations or audit facts.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM recurring_availability_rules LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: recurring availability data exists")
    if connection.execute(sa.text(
        "SELECT 1 FROM history_events WHERE entity_type = 'AVAILABILITY_RULE' LIMIT 1"
    )).first():
        raise RuntimeError("cannot downgrade: recurring availability audit data exists")
    _history_constraint(_OLD)
    op.drop_table("recurring_availability_revisions")
    op.drop_index("ix_recurring_rules_owner", table_name="recurring_availability_rules")
    op.drop_table("recurring_availability_rules")
