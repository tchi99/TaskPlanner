"""TP-080B integration tests on a throwaway PostgreSQL 16 database.

Never connect these tests to a production database. The CI job supplies a
dedicated local database; offline SQLite tests skip this module.
"""
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.application.projects import create_project
from app.application.segments import add_segment
from app.application.tasks import CaptureTaskCommand, capture_task
from app.application.weekly import decide_weekly
from app.domain import Task, TaskStatus
from app.domain.weekly import WeeklyAction, WeeklySubject
from app.infrastructure.db import create_taskplanner_engine
from app.infrastructure.models import (
    DailyReviewRecord, HistoryEventRecord, TaskRecord, WorkSessionRecord,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


@pytest.fixture(scope="module")
def postgres_engine():
    url = os.getenv("TASKPLANNER_PG_TEST_URL")
    if not url:
        pytest.skip("No disposable PostgreSQL instance configured")
    parsed = make_url(url)
    # The suite deletes its schema and must never be pointed at Supabase.
    if parsed.host not in ("127.0.0.1", "localhost") or parsed.database != "taskplanner_test":
        pytest.fail("Refusing destructive PostgreSQL test outside local taskplanner_test")

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS taskplanner CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA taskplanner")
    finally:
        admin.dispose()

    env = {
        **os.environ,
        "TASKPLANNER_DATABASE_URL": url,
        "TASKPLANNER_DATABASE_SCHEMA": "taskplanner",
        "TASKPLANNER_ENV": "test",
        "TASKPLANNER_AUTH_MODE": "local",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )
    engine = create_taskplanner_engine(url, environment="test", schema="taskplanner")
    try:
        yield engine
    finally:
        engine.dispose()


def test_secure_connection_policy_and_fresh_schema(postgres_engine):
    assert {"projects", "tasks", "task_segments", "history_events",
            "work_sessions", "weekly_decisions", "daily_reviews",
            "recurring_availability_rules", "recurring_availability_revisions"} <= set(
                inspect(postgres_engine).get_table_names(schema="taskplanner")
            )
    assert "tasks" not in inspect(postgres_engine).get_table_names(schema="public")
    with postgres_engine.connect() as connection:
        assert connection.scalar(text("SELECT current_schema()")) == "taskplanner"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_tp022a"
        assert connection.scalar(text(
            "SELECT pg_get_serial_sequence('taskplanner.history_events', 'sequence')"
        ))
        definition = connection.scalar(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'taskplanner' "
            "AND indexname = 'uq_work_sessions_single_active'"
        ))
        assert definition and "WHERE" in definition and "ACTIVE" in definition

    for bad in (
        "sqlite:///./production.db",
        "postgresql+psycopg://user:pass@localhost/db?sslmode=disable",
    ):
        with pytest.raises(ValueError):
            create_taskplanner_engine(bad, environment="production")
    with pytest.raises(ValueError):
        create_taskplanner_engine(
            "postgresql+psycopg://user:pass@localhost/db",
            environment="production", schema="public",
        )


def test_project_capture_segments_json_decisions_and_utc(postgres_engine):
    factory = sessionmaker(
        bind=postgres_engine, autoflush=False, expire_on_commit=False
    )
    project = create_project(SqlAlchemyUnitOfWork(factory), "Postgres project")
    captured = capture_task(
        SqlAlchemyUnitOfWork(factory),
        CaptureTaskCommand(
            title="Capture", estimated_minutes=45,
            due_at=datetime(2026, 10, 11, 10, tzinfo=timezone(timedelta(hours=-4))),
        ),
    )
    task = Task(title="Executable", status=TaskStatus.TODO, project_id=project.id)
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()
    aggregate = add_segment(SqlAlchemyUnitOfWork(factory), task.id, "First segment", 30)
    assert len(aggregate.segments) == 1
    assert aggregate.segments[0].estimated_minutes == 30

    chosen = decide_weekly(
        SqlAlchemyUnitOfWork(factory), date(2026, 10, 5), "America/Toronto",
        WeeklySubject.TASK, task.id, WeeklyAction.REVIEW_LATER,
        date(2026, 10, 12), 0,
    )
    assert chosen.revision == 1

    with Session(postgres_engine) as session:
        session.add(DailyReviewRecord(
            day=date(2026, 10, 10), timezone_name="America/Toronto",
            selected_task_ids=[str(task.id)], state="OPEN",
            followups=[{"kind": "review", "id": str(task.id)}], revision=1,
        ))
        session.commit()

    with SqlAlchemyUnitOfWork(factory) as uow:
        assert uow.projects.get(project.id) is not None
        assert len(uow.tasks.get_aggregate(task.id).segments) == 1
        assert len(uow.weekly_reviews.list_week(date(2026, 10, 5), "America/Toronto")) == 1

    with Session(postgres_engine) as session:
        event = session.scalar(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_id == str(captured.id)
        ))
        assert event is not None
        assert event.sequence > 0
        assert event.payload["estimated_minutes"] == 45
        assert event.recorded_at.tzinfo is not None
        stored = session.get(TaskRecord, str(captured.id))
        assert stored is not None
        assert stored.due_at == datetime(2026, 10, 11, 14, tzinfo=UTC)
        daily = session.get(DailyReviewRecord, (date(2026, 10, 10), "America/Toronto"))
        assert daily.selected_task_ids == [str(task.id)]
        assert session.scalar(text(
            "SELECT pg_typeof(decided_at)::text FROM weekly_decisions LIMIT 1"
        )) == "timestamp with time zone"


def test_work_sessions_partial_unique_and_timezones(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)
    task = capture_task(SqlAlchemyUnitOfWork(factory), CaptureTaskCommand(title="Session task"))
    now = datetime(2026, 10, 10, 20, tzinfo=UTC)

    def make_session(status, suffix):
        return WorkSessionRecord(
            id=str(uuid4()), task_id=str(task.id), segment_id=None,
            started_at=now, active_since=now if status == "ACTIVE" else None,
            finished_at=now + timedelta(minutes=15) if status == "FINISHED" else None,
            active_seconds=900 if status == "FINISHED" else 0,
            interruptions=0, status=status, revision=1,
            work_type_id=None, estimated_minutes=None, planned_minutes=None,
        )

    with Session(postgres_engine) as session:
        session.add_all([make_session("FINISHED", 1), make_session("FINISHED", 2),
                         make_session("ACTIVE", 3)])
        session.commit()

    with Session(postgres_engine) as session:
        assert all(row.started_at.tzinfo is not None for row in session.scalars(
            select(WorkSessionRecord).where(WorkSessionRecord.task_id == str(task.id))
        ))
        session.add(make_session("ACTIVE", 4))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_invalid_history_rolls_back_task_atomically(postgres_engine):
    task_id = str(uuid4())
    now = datetime(2026, 10, 10, 20, tzinfo=UTC)
    with Session(postgres_engine) as session:
        session.add(TaskRecord(
            id=task_id, title="Should rollback", project_id=None,
            notes=None, status="INBOX", protection="REPLANNABLE",
            work_type_id=None, estimated_minutes=None, due_at=None,
            created_at=now,
        ))
        session.add(HistoryEventRecord(
            id=str(uuid4()), occurred_at=now, recorded_at=now,
            entity_type="TASK", entity_id=task_id, task_id=task_id,
            event_type="TASK_CAPTURED", schema_version=1, source="INVALID",
            reason_code=None, correlation_id=str(uuid4()), causation_id=None,
            payload={"test": True},
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with Session(postgres_engine) as session:
        assert session.get(TaskRecord, task_id) is None
        assert session.scalar(select(HistoryEventRecord).where(
            HistoryEventRecord.task_id == task_id
        )) is None
