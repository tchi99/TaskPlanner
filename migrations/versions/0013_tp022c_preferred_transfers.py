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
    if op.get_bind().dialect.name == "sqlite":
        # SQLite supports adding a nullable REFERENCES column in-place.
        # Rebuilding this legacy table would revalidate unrelated old task FKs.
        op.execute(sa.text(
            "ALTER TABLE confirmed_time_blocks "
            "ADD COLUMN transferred_from_work_type_id VARCHAR(36) "
            "CONSTRAINT fk_confirmed_time_blocks_transfer_work_type "
            "REFERENCES work_types(id) ON DELETE RESTRICT"
        ))
    else:
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
    if bind.dialect.name == "sqlite":
        # In-place DROP likewise preserves legacy rows without a table copy.
        op.execute(sa.text(
            "ALTER TABLE confirmed_time_blocks "
            "DROP COLUMN transferred_from_work_type_id"
        ))
    else:
        with op.batch_alter_table("confirmed_time_blocks") as batch:
            batch.drop_column("transferred_from_work_type_id")
