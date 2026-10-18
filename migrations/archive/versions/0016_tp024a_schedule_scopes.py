"""TP-024A additive schedule scopes, affiliations and provenance.

Revision ID: 0016_tp024a
Revises: 0015_tp023a
All pre-existing rows retain NULL scope provenance; no name-based inference.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_tp024a"
down_revision = "0015_tp023a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_scopes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_compatibility", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("version > 0", name="ck_schedule_scope_version"),
        sa.CheckConstraint("state IN ('ACTIVE','INACTIVE')", name="ck_schedule_scope_state"),
        sa.UniqueConstraint("owner_id", "name", name="uq_schedule_scope_owner_name"),
    )
    op.create_index("ix_schedule_scopes_owner", "schedule_scopes", ["owner_id"])
    op.create_table(
        "work_type_scope_versions",
        sa.Column("owner_id", sa.String(128), primary_key=True),
        sa.Column("work_type_id", sa.String(36), sa.ForeignKey("work_types.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "work_type_scope_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("work_type_id", sa.String(36), sa.ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_id", sa.String(36), sa.ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "work_type_id", "version", name="uq_scope_assignment_version"),
    )
    op.create_index("ix_scope_assignment_lookup", "work_type_scope_assignments",
                    ["owner_id", "work_type_id", "effective_from", "version"])
    op.create_table(
        "scope_change_commands",
        sa.Column("owner_id", sa.String(128), primary_key=True),
        sa.Column("command_id", sa.String(36), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scope_change_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("command_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scope_audit_owner", "scope_change_audit", ["owner_id", "recorded_at"])
    for table in ("recurring_availability_revisions", "availability_exceptions",
                  "availability_blocks", "confirmed_time_blocks"):
        if op.get_bind().dialect.name == "sqlite":
            # Native ADD COLUMN preserves legacy rows, including old references
            # that a batch copy would revalidate against unrelated tables.
            # Nullable FK columns are supported by SQLite's native ALTER TABLE.
            op.execute(sa.text(
                f'ALTER TABLE "{table}" ADD COLUMN "scope_id" VARCHAR(36) '
                'REFERENCES schedule_scopes(id) ON DELETE RESTRICT'
            ))
        else:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("scope_id", sa.String(36), nullable=True))
                batch.create_foreign_key(
                    f"fk_{table}_scope_id", "schedule_scopes", ["scope_id"], ["id"],
                    ondelete="RESTRICT",
                )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("recurring_availability_revisions", "availability_exceptions",
                  "availability_blocks", "confirmed_time_blocks"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE scope_id IS NOT NULL LIMIT 1")).first():
            raise RuntimeError("cannot downgrade scoped schedule provenance")
    for table in ("scope_change_audit", "scope_change_commands", "work_type_scope_assignments",
                  "work_type_scope_versions", "schedule_scopes"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("cannot downgrade initialized schedule scopes or commands")
    # The scope_id columns were added with native SQLite ALTER TABLE.
    # Drop those columns natively as well: a batch copy begins DML and a
    # mid-migration commit would leave Alembic's version update uncommitted.
    # Native DROP COLUMN keeps legacy rows (including unrelated orphaned
    # references) intact and removes the column's FK without rebuilding.
    for table in ("confirmed_time_blocks", "availability_blocks",
                  "availability_exceptions", "recurring_availability_revisions"):
        if bind.dialect.name == "sqlite":
            bind.exec_driver_sql(f'ALTER TABLE "{table}" DROP COLUMN "scope_id"')
        else:
            with op.batch_alter_table(table) as batch:
                batch.drop_constraint(f"fk_{table}_scope_id", type_="foreignkey")
                batch.drop_column("scope_id")
    op.drop_index("ix_scope_audit_owner", table_name="scope_change_audit")
    op.drop_table("scope_change_audit")
    op.drop_table("scope_change_commands")
    op.drop_index("ix_scope_assignment_lookup", table_name="work_type_scope_assignments")
    op.drop_table("work_type_scope_assignments")
    op.drop_table("work_type_scope_versions")
    op.drop_index("ix_schedule_scopes_owner", table_name="schedule_scopes")
    op.drop_table("schedule_scopes")
