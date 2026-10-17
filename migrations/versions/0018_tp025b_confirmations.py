"""TP-025B: durable owner-scoped booking confirmation receipts.

Revision ID: 0018_tp025b
Revises: 0017_tp025a
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_tp025b"
down_revision = "0017_tp025a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "time_block_confirmation_commands",
        sa.Column("owner_id", sa.String(128), primary_key=True),
        sa.Column("command_id", sa.String(36), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_time_block_command_owner",
                    "time_block_confirmation_commands", ["owner_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(
            "SELECT 1 FROM time_block_confirmation_commands LIMIT 1")).first():
        raise RuntimeError("cannot downgrade: booking command receipts must be retained")
    op.drop_index("ix_time_block_command_owner",
                  table_name="time_block_confirmation_commands")
    op.drop_table("time_block_confirmation_commands")
