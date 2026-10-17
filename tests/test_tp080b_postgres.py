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
            "recurring_availability_rules", "recurring_availability_revisions",
            "availability_exceptions", "schedule_scopes",
            "work_type_scope_assignments", "scope_change_commands",
            "scope_change_audit", "eligibility_series", "eligibility_revisions",
            "eligibility_exceptions", "eligibility_exception_revisions"} <= set(
                inspect(postgres_engine).get_table_names(schema="taskplanner")
            )
    assert "tasks" not in inspect(postgres_engine).get_table_names(schema="public")
    with postgres_engine.connect() as connection:
        assert connection.scalar(text("SELECT current_schema()")) == "taskplanner"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0017_tp025a"
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


def test_tp022a_recurring_rules_round_trip_in_private_postgres(postgres_engine):
    """Exercise the Alembic-created tables, JSON weekdays and CAS on PostgreSQL."""
    from app.application.projects import create_work_type
    from app.application.recurring_availability import (
        create_rule, get_rule, revise_rule, read_occurrences,
    )
    from app.domain.recurring_availability import AvailabilityMode, RuleConflict, RuleKind
    from zoneinfo import ZoneInfo

    factory = sessionmaker(
        bind=postgres_engine, autoflush=False, expire_on_commit=False
    )
    focus = create_work_type(SqlAlchemyUnitOfWork(factory), "TP-022A PG focus")
    start = datetime.now(ZoneInfo("America/Toronto")).date() + timedelta(days=14)
    payload = {
        "effective_from": start, "valid_until": None,
        "timezone_name": "America/Toronto", "days_of_week": (1, 3),
        "starts_at_local": "09:00", "ends_at_local": "11:30",
        "kind": RuleKind.CATEGORIZED, "work_type_id": focus.id,
        "mode": AvailabilityMode.PROTECTED, "enabled": True,
        "start_fold": None, "end_fold": None,
    }
    value = create_rule(SqlAlchemyUnitOfWork(factory), "pg-owner", payload)
    assert get_rule(SqlAlchemyUnitOfWork(factory), "pg-owner", value.id).version == 1
    found, issues = read_occurrences(
        SqlAlchemyUnitOfWork(factory), "pg-owner", start, start + timedelta(days=7)
    )
    assert len(found) == 2 and not issues
    revised = revise_rule(
        SqlAlchemyUnitOfWork(factory), "pg-owner", value.id, 1,
        {**payload, "effective_from": start + timedelta(days=7)},
    )
    assert revised.version == 2
    with pytest.raises(RuleConflict):
        revise_rule(
            SqlAlchemyUnitOfWork(factory), "pg-owner", value.id, 1,
            {**payload, "effective_from": start + timedelta(days=14)},
        )
    with postgres_engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT COUNT(*) FROM recurring_availability_revisions WHERE rule_id = :id"
        ), {"id": str(value.id)}) == 2
        assert connection.scalar(text(
            "SELECT COUNT(*) FROM history_events "
            "WHERE entity_type = 'AVAILABILITY_RULE' AND entity_id = :id"
        ), {"id": str(value.id)}) == 2



def test_tp022b_exception_preview_persistence_and_audit_in_postgres(postgres_engine):
    """Exercise the new exception table and offset-preserving persistence on PG."""
    from datetime import time
    from zoneinfo import ZoneInfo
    from app.domain.availability_exceptions import ExceptionAction
    from app.domain.recurring_availability import RuleKind
    from app.application.effective_availability import (
        get_exception, preview_exception, read_effective, save_exception,
    )

    owner = "tp-022b-pg-test"
    factory = sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)
    zone = ZoneInfo("America/Toronto")
    tomorrow_week = datetime.now(zone).date() + timedelta(days=14)
    fields = {
        "action": ExceptionAction.ADD,
        "timezone_name": "America/Toronto",
        "starts_at": datetime.combine(tomorrow_week, time(9), zone),
        "ends_at": datetime.combine(tomorrow_week, time(10), zone),
        "kind": RuleKind.GENERAL,
    }
    token, projected, _ = preview_exception(
        SqlAlchemyUnitOfWork(factory), owner, fields,
    )
    assert projected.declared_minutes == 60
    made = save_exception(SqlAlchemyUnitOfWork(factory), owner, fields, token, False)
    fetched = get_exception(SqlAlchemyUnitOfWork(factory), owner, made.id)
    assert fetched.version == 1 and fetched.starts_at.utcoffset() == fields["starts_at"].utcoffset()
    current = read_effective(SqlAlchemyUnitOfWork(factory), owner,
                             tomorrow_week, tomorrow_week + timedelta(days=1),
                             "America/Toronto")
    assert current.declared_minutes == 60
    disabled = {**fields, "enabled": False}
    second, _, _ = preview_exception(
        SqlAlchemyUnitOfWork(factory), owner, disabled,
        exception_id=made.id, expected_version=1,
    )
    updated = save_exception(SqlAlchemyUnitOfWork(factory), owner, disabled,
                             second, False, exception_id=made.id, expected_version=1)
    assert updated.version == 2
    assert read_effective(SqlAlchemyUnitOfWork(factory), owner,
                          tomorrow_week, tomorrow_week + timedelta(days=1),
                          "America/Toronto").declared_minutes == 0
    with postgres_engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT COUNT(*) FROM history_events "
            "WHERE entity_type = 'AVAILABILITY_EXCEPTION' AND entity_id = :id"
        ), {"id": str(made.id)}) == 2


def test_tp023a_atomic_weekly_edit_on_private_postgres(postgres_engine):
    """Multi-day split, idempotent receipt and temporal revision in PostgreSQL."""
    from app.application.recurring_availability import create_rule, revise_rule
    from app.application.weekly_schedule import (
        WeeklyDraft, Section, Slot, preview_weekly, confirm_weekly,
    )
    from app.domain.recurring_availability import RuleKind, expand_rules

    factory = sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)
    owner = "tp023a-pg-owner"
    effect = datetime.now(__import__("zoneinfo").ZoneInfo("America/Toronto")).date() + timedelta(days=21)
    while effect.weekday() != 0:
        effect += timedelta(days=1)
    fields = {
        "effective_from": effect, "valid_until": None, "timezone_name": "America/Toronto",
        "days_of_week": (0, 1, 2), "starts_at_local": "09:00",
        "ends_at_local": "10:00", "kind": RuleKind.GENERAL,
        "work_type_id": None, "mode": None, "enabled": True,
        "start_fold": None, "end_fold": None,
    }
    original = create_rule(SqlAlchemyUnitOfWork(factory), owner, fields)
    later = effect + timedelta(days=28)
    revised = revise_rule(SqlAlchemyUnitOfWork(factory), owner, original.id, 1, {
        **fields, "effective_from": later, "starts_at_local": "10:00",
        "ends_at_local": "11:00",
    })
    draft = WeeklyDraft(
        effect + timedelta(days=7), "America/Toronto",
        (Section(1, RuleKind.GENERAL, None, (Slot("13:00", "14:00"),)),),
        {str(original.id): revised.version},
    )
    token = preview_weekly(SqlAlchemyUnitOfWork(factory), owner, draft)
    assert token["has_changes"] and len(token["derived_rule_ids"]) == 2
    command_id = uuid4()
    receipt = confirm_weekly(SqlAlchemyUnitOfWork(factory), owner, draft,
                             command_id=command_id, fingerprint=token["fingerprint"],
                             confirmed=True, acknowledge_conflicts=False)
    replay = confirm_weekly(SqlAlchemyUnitOfWork(factory), owner, draft,
                            command_id=command_id, fingerprint=token["fingerprint"],
                            confirmed=True, acknowledge_conflicts=False)
    assert receipt == replay
    with SqlAlchemyUnitOfWork(factory) as uow:
        rules = tuple(uow.recurring_availability.list_owner(owner))
        assert len(rules) == 4
        occurrences, problems = expand_rules(rules, later, later+timedelta(days=3))
        assert not problems
        assert len(occurrences) == 3
        by_weekday = {occ.original_local_date.weekday(): occ for occ in occurrences}
        assert {day: occ.starts_at.astimezone(
            __import__("zoneinfo").ZoneInfo("America/Toronto")
        ).hour for day, occ in by_weekday.items()} == {0: 10, 1: 13, 2: 10}
    with Session(postgres_engine) as session:
        assert session.scalar(text(
            "SELECT COUNT(*) FROM weekly_schedule_commands WHERE owner_id = :owner"
        ), {"owner": owner}) == 1
        assert session.scalar(text(
            "SELECT COUNT(*) FROM recurring_availability_revisions "
            "WHERE rule_id = :id AND supersedes_future"
        ), {"id": str(original.id)}) == 1


def test_tp024a_postgres_parent_owner_history_and_version_cas(postgres_engine):
    """The real PG schema supports scope affiliation without touching WorkType IDs."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.application.schedule_scopes import (
        AffiliationDraft, create_scope, preview_affiliation, confirm_affiliation,
    )
    from app.domain import WorkType
    from app.domain.recurring_availability import RuleConflict
    from app.domain.schedule_scopes import compatibility_scope_id, effective_scope

    owner = "test:tp024a:" + str(uuid4())
    foreign_owner = "test:tp024a:" + str(uuid4())
    factory = sessionmaker(bind=postgres_engine, autoflush=False, expire_on_commit=False)
    new_type = WorkType(name="TP024A-" + str(uuid4()))
    with SqlAlchemyUnitOfWork(factory) as unit:
        unit.work_types.add(new_type)
        unit.commit()
    scope = create_scope(SqlAlchemyUnitOfWork(factory), owner, "Travail")
    assert scope.owner_id == owner
    with SqlAlchemyUnitOfWork(factory) as unit:
        assert unit.schedule_scopes.get(foreign_owner, scope.id) is None
    day = datetime.now(ZoneInfo("America/Toronto")).date() + timedelta(days=3)
    draft = AffiliationDraft(new_type.id, scope.id, day, "America/Toronto", 0, 1)
    preview = preview_affiliation(SqlAlchemyUnitOfWork(factory), owner, draft)
    cmd = uuid4()
    confirmed = confirm_affiliation(
        SqlAlchemyUnitOfWork(factory), owner, draft,
        fingerprint=preview["fingerprint"], command_id=cmd,
        confirmed=True, acknowledge_bookings=False,
    )
    assert confirmed["applied"] and confirmed["affiliation_version"] == 1
    assert confirmed == confirm_affiliation(
        SqlAlchemyUnitOfWork(factory), owner, draft,
        fingerprint=preview["fingerprint"], command_id=cmd,
        confirmed=True, acknowledge_bookings=False,
    )
    with SqlAlchemyUnitOfWork(factory) as unit:
        history = unit.schedule_scopes.affiliations(owner)
        assert len(history) == 1
        assert effective_scope(new_type.id, day, history,
                               compatibility_scope_id(owner)) == scope.id
        assert effective_scope(new_type.id, day-timedelta(days=1), history,
                               compatibility_scope_id(owner)) == compatibility_scope_id(owner)
        assert unit.schedule_scopes.affiliations(foreign_owner) == ()
    with pytest.raises(RuleConflict):
        preview_affiliation(SqlAlchemyUnitOfWork(factory), owner, draft)
