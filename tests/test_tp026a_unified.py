"""TP-026A: real parents, fresh databases and non-additive typed admission."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.projects import create_work_type
from app.domain.capacity import AvailabilityBlock, CapacityStatus
from app.domain.eligibility_capacity import evaluate_eligibility_week
from app.domain.eligibility_allocator import suggest_eligible_blocks
from app.domain.eligibility_projection import (
    EligibilityChoice, EligibilityProjection, PhysicalEligibilityFragment,
)
from app.domain.model import Task
from app.domain.task_rules import TaskAggregate
from app.infrastructure import models  # noqa
from app.infrastructure.db import Base
from app.infrastructure.models import WorkTypeRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app

OWNER = "urn:taskplanner:local"
WEEK = date(2027, 1, 4)
ZONE = "America/Toronto"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_empty_install_direct_parented_work_type_and_immutable_parent(runtime):
    client, factory, engine = runtime
    assert client.get("/api/schedule-scopes").json() == {"scopes": []}
    assert client.get("/api/work-types").json() == []
    assert client.post("/api/work-types", json={"name": "Focus"}).status_code == 422
    missing = client.post("/api/work-types", json={
        "name": "Focus", "scope_id": str(uuid4())})
    assert missing.status_code == 422
    created = client.post("/api/schedule-scopes", json={"name": "Travail"})
    assert created.status_code == 201, created.text
    scope = created.json()["id"]
    leaf = client.post("/api/work-types", json={
        "name": "Focus", "scope_id": scope})
    assert leaf.status_code == 201, leaf.text
    value = leaf.json()
    assert value["scope_id"] == scope and value["version"] == 1
    assert client.get("/api/work-types").json() == [value]
    assert client.patch("/api/work-types/" + value["id"], json={
        "name": "Focus", "expected_version": 1, "scope_id": str(uuid4()),
    }).status_code == 422
    revised = client.patch("/api/work-types/" + value["id"], json={
        "name": "Focus profond", "expected_version": 1})
    assert revised.status_code == 200, revised.text
    assert revised.json()["scope_id"] == scope
    assert revised.json()["version"] == 2
    assert client.patch("/api/work-types/" + value["id"], json={
        "name": "Brouillon périmé", "expected_version": 1}).status_code == 409
    with factory() as session:
        row = session.scalar(select(WorkTypeRecord).where(WorkTypeRecord.id == value["id"]))
        assert row.scope_id == scope
    columns = {col["name"]: col for col in inspect(engine).get_columns("work_types")}
    assert not columns["scope_id"]["nullable"]
    assert "is_compatibility" not in {
        col["name"] for col in inspect(engine).get_columns("schedule_scopes")}
    assert "work_type_scope_assignments" not in inspect(engine).get_table_names()


def test_owner_mismatch_cannot_create_orphan_in_transaction(runtime):
    client, factory, engine = runtime
    parent = client.post("/api/schedule-scopes", json={"name": "Personnel"}).json()["id"]
    with pytest.raises(ValueError, match="parent scope"):
        create_work_type(SqlAlchemyUnitOfWork(factory), "Secret", None,
                         UUID(parent), "other-owner")
    with factory() as session:
        assert session.scalars(select(WorkTypeRecord)).all() == []


def test_two_permissions_one_physical_interval_and_no_null_booking():
    parent, focus, meeting = uuid4(), uuid4(), uuid4()
    begin = datetime(2027, 1, 5, 10, tzinfo=timezone.utc)
    end = begin + timedelta(minutes=120)
    fragment = PhysicalEligibilityFragment(
        begin, end, parent, ("RULE:parent",),
        (EligibilityChoice(focus, 1, ("FOCUS",)),
         EligibilityChoice(meeting, 2, ("MEETING",))), False,
    )
    projection = EligibilityProjection(
        (fragment,), (), (), 120, ((focus, 120), (meeting, 120)),
    )
    block = AvailabilityBlock(WEEK, begin, end, scope_id=parent)
    focused = TaskAggregate(Task(title="Focus", work_type_id=focus,
                                 estimated_minutes=120))
    meeting_task = TaskAggregate(Task(title="Meeting", work_type_id=meeting,
                                      estimated_minutes=120))
    unclassified = TaskAggregate(Task(title="Capture", estimated_minutes=30))
    offer = suggest_eligible_blocks(
        WEEK, ZONE, projection, (), (),
        (unclassified,), availability_fingerprint="snapshot",
        work_type_scopes={focus: parent, meeting: parent},
    )
    assert not offer.suggestions
    assert offer.unplaced[0].reason == "UNCLASSIFIED_WORK_TYPE"
    competing = suggest_eligible_blocks(
        WEEK, ZONE, projection, (), (), (focused, meeting_task),
        availability_fingerprint="snapshot",
        work_type_scopes={focus: parent, meeting: parent},
    )
    assert sum(s.minutes for s in competing.suggestions) <= 120
    assert competing.unplaced and not competing.can_confirm
    outcome = evaluate_eligibility_week(
        WEEK, ZONE, (block,), projection, (focused, meeting_task),
    )
    assert outcome.available_minutes == 120
    assert outcome.known_demand_minutes == 240
    assert outcome.status is CapacityStatus.OVER_CAPACITY


def _alembic(database: Path):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{database}",
             "TASKPLANNER_ENV": "test", "TASKPLANNER_AUTH_MODE": "local"},
        check=False,
    )


def test_alembic_fresh_root_and_refusal_to_touch_old_tables(tmp_path):
    fresh = tmp_path / "fresh.sqlite"
    upgraded = _alembic(fresh)
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(fresh) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0020_tp026_fresh",)
        assert connection.execute("SELECT count(*) FROM schedule_scopes").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM work_types").fetchone() == (0,)
        assert "scope_id" in {row[1] for row in
                               connection.execute("PRAGMA table_info(work_types)")}
        assert "work_type_scope_assignments" not in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
    legacy = tmp_path / "legacy.sqlite"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE existing_data (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO existing_data VALUES (42)")
    refused = _alembic(legacy)
    assert refused.returncode != 0
    with sqlite3.connect(legacy) as connection:
        assert connection.execute("SELECT id FROM existing_data").fetchone() == (42,)
