"""TP-022C: persist explicit accepted PREFERRED transfer provenance.

Revision ID: 0013_tp022c
Revises: 0012_tp022b
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_tp022c"
down_revision = "0012_tp022b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("confirmed_time_blocks") as batch:
        batch.add_column(sa.Column(
            "transferred_from_work_type_id", sa.String(36),
            sa.ForeignKey("work_types.id", ondelete="RESTRICT",
                          name="fk_confirmed_time_blocks_transfer_work_type"),
            nullable=True,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(
        "SELECT 1 FROM confirmed_time_blocks "
        "WHERE transferred_from_work_type_id IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("cannot downgrade: accepted PREFERRED transfers exist")
    with op.batch_alter_table("confirmed_time_blocks") as batch:
        batch.drop_column("transferred_from_work_type_id")
