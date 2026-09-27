"""TP-011B persistence, foreign keys and behavioral history.

Revision ID: 0002_tp011b
Revises: 0001_tasks
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_tp011b"
down_revision = "0001_tasks"
branch_labels = None
depends_on = None

_TASK_STATUS = "status IN ('INBOX','TODO','IN_PROGRESS','DONE','CANCELLED')"
_PROTECTION = "protection IN ('PROTECTED','REPLANNABLE','FLEXIBLE')"
_SEGMENT_STATUS = "status IN ('TODO','IN_PROGRESS','DONE','CANCELLED')"


def _assert_no_orphans() -> None:
    connection = op.get_bind()
    project_orphan = connection.execute(
        sa.text(
            "SELECT id, project_id FROM tasks "
            "WHERE project_id IS NOT NULL LIMIT 1"
        )
    ).first()
    if project_orphan is not None:
        raise RuntimeError(
            "Cannot migrate tasks.project_id: "
            f"task {project_orphan.id} references missing project "
            f"{project_orphan.project_id}"
        )

    work_type_orphan = connection.execute(
        sa.text(
            "SELECT id, work_type_id FROM tasks "
            "WHERE work_type_id IS NOT NULL LIMIT 1"
        )
    ).first()
    if work_type_orphan is not None:
        raise RuntimeError(
            "Cannot migrate tasks.work_type_id: "
            f"task {work_type_orphan.id} references missing work type "
            f"{work_type_orphan.work_type_id}"
        )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','ARCHIVED')",
            name="ck_projects_status",
        ),
    )
    op.create_table(
        "work_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )

    _assert_no_orphans()

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_tasks_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_tasks_work_type_id_work_types",
            "work_types",
            ["work_type_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint("ck_tasks_status", _TASK_STATUS)
        batch.create_check_constraint("ck_tasks_protection", _PROTECTION)
        batch.create_check_constraint(
            "ck_tasks_estimated_minutes",
            "estimated_minutes IS NULL OR estimated_minutes > 0",
        )

    op.create_table(
        "task_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "work_type_id",
            sa.String(36),
            sa.ForeignKey("work_types.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "task_id",
            "position",
            name="uq_task_segments_task_position",
        ),
        sa.CheckConstraint(
            _SEGMENT_STATUS,
            name="ck_task_segments_status",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_task_segments_position",
        ),
        sa.CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes > 0",
            name="ck_task_segments_estimated_minutes",
        ),
    )
    op.create_index(
        "ix_task_segments_task_position",
        "task_segments",
        ["task_id", "position"],
        unique=False,
    )

    op.create_table(
        "history_events",
        sa.Column(
            "sequence",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("id", sa.String(36), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("causation_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('TASK','SEGMENT')",
            name="ck_history_events_entity_type",
        ),
        sa.CheckConstraint(
            "source IN ('USER','SYSTEM_RULE','IMPORT','AI')",
            name="ck_history_events_source",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_history_events_schema_version",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_history_events_task_sequence",
        "history_events",
        ["task_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_history_events_entity_sequence",
        "history_events",
        ["entity_type", "entity_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_history_events_correlation_sequence",
        "history_events",
        ["correlation_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_history_events_correlation_sequence",
        table_name="history_events",
    )
    op.drop_index(
        "ix_history_events_entity_sequence",
        table_name="history_events",
    )
    op.drop_index(
        "ix_history_events_task_sequence",
        table_name="history_events",
    )
    op.drop_table("history_events")

    op.drop_index(
        "ix_task_segments_task_position",
        table_name="task_segments",
    )
    op.drop_table("task_segments")

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint("ck_tasks_estimated_minutes", type_="check")
        batch.drop_constraint("ck_tasks_protection", type_="check")
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.drop_constraint(
            "fk_tasks_work_type_id_work_types",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_tasks_project_id_projects",
            type_="foreignkey",
        )

    op.drop_table("work_types")
    op.drop_table("projects")
