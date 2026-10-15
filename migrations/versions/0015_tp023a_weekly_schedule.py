"""TP-023A: temporal supersession and durable atomic-command receipts.

Revision ID: 0015_tp023a
Revises: 0014_tp022r
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_tp023a"
down_revision = "0014_tp022r"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The old uniqueness prohibited a second recorded revision at the same
    # civil date. Record order is now (effective_from, number).
    with op.batch_alter_table("recurring_availability_revisions",
                              recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto") as batch:
        batch.drop_constraint("uq_recurring_revision_effective", type_="unique")
        batch.add_column(sa.Column("supersedes_future", sa.Boolean(),
                                   nullable=False, server_default=sa.false()))
    op.create_table(
        "weekly_schedule_commands",
        sa.Column("owner_id", sa.String(128), primary_key=True),
        sa.Column("command_id", sa.String(36), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_weekly_commands_owner", "weekly_schedule_commands", ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM weekly_schedule_commands LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: weekly edit receipts exist")
    if bind.execute(sa.text("SELECT 1 FROM recurring_availability_revisions "
                            "WHERE supersedes_future LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: future supersession exists")
    if bind.execute(sa.text("SELECT 1 FROM recurring_availability_revisions "
                            "GROUP BY rule_id, effective_from HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: duplicate civil effective dates exist")
    op.drop_index("ix_weekly_commands_owner", table_name="weekly_schedule_commands")
    op.drop_table("weekly_schedule_commands")
    with op.batch_alter_table("recurring_availability_revisions",
                              recreate="always" if bind.dialect.name == "sqlite" else "auto") as batch:
        batch.drop_column("supersedes_future")
        batch.create_unique_constraint("uq_recurring_revision_effective", ["rule_id", "effective_from"])
