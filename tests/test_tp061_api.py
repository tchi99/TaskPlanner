"""TP-061 weekly snapshots, explicit decisions, stale revision and no task side effects."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app

WEEK = "2026-10-05"
ZONE = "America/Toronto"
URL = "/api/review/weekly"


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def task(client, title="Item", *, clarify=True, due_at=None):
    payload = {"title": title}
    if due_at:
        payload["due_at"] = due_at
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    if clarify:
        response = client.post("/api/tasks/" + task_id + "/clarify", json={})
        assert response.status_code == 200, response.text
    return task_id


def snapshot(client, week=WEEK, zone=ZONE):
    return client.get(URL, params={"week_start": week, "timezone_name": zone})


def decide(client, kind, target, action="RECIRCULATE", revision=0, review_on=None,
           confirmed=True, week=WEEK):
    return client.post(URL + "/decide", json={
        "week_start": week, "timezone_name": ZONE,
        "subject_kind": kind, "subject_id": target, "action": action,
        "review_on": review_on, "expected_revision": revision, "confirmed": confirmed,
    })


def test_snapshot_shows_capacity_protected_drift_inbox_and_projects(setup):
    client, _ = setup
    project_response = client.post("/api/projects", json={"title": "Active project"})
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    protected = task(client, "Urgent", due_at="2026-10-01T12:00:00Z")
    inbox = task(client, "Unclarified", clarify=False)
    assert client.patch("/api/tasks/" + protected + "/protection",
                        json={"protection": "PROTECTED"}).status_code == 200
    before = client.get("/api/tasks").json()
    result = snapshot(client)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["week_start"] == WEEK
    assert value["calendar_written"] is False
    assert value["tasks_modified"] is False
    assert value["is_hypothetical"] is True
    assert value["manual_block_count"] == 0
    assert value["capacity_if_all_open"]["unestimated_units"] == 1
    assert [t["task_id"] for t in value["protected"]] == [protected]
    assert [t["task_id"] for t in value["drifted"]] == [protected]
    assert [t["task_id"] for t in value["inbox"]] == [inbox]
    assert [p["project_id"] for p in value["projects_without_next_action"]] == [project_id]
    assert client.get("/api/tasks").json() == before


def test_confirmed_decisions_are_revisable_but_not_applied_to_tasks(setup):
    client, _ = setup
    task_id = task(client, "To review")
    before = client.get("/api/tasks/" + task_id).json()
    assert decide(client, "TASK", task_id, confirmed=False).status_code == 422
    assert snapshot(client).json()["decisions"] == []
    assert decide(client, "TASK", task_id, action="POSTPONE").status_code == 422
    assert decide(client, "TASK", task_id, action="REVIEW_LATER",
                  review_on="2026-10-08").status_code == 422
    first = decide(client, "TASK", task_id, action="REVIEW_LATER",
                   review_on="2026-10-13")
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1
    assert first.json()["review_on"] == "2026-10-13"
    assert decide(client, "TASK", task_id, "ABANDON", revision=0).status_code == 409
    second = decide(client, "TASK", task_id, "ABANDON", revision=1)
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == 2
    assert second.json()["review_on"] is None
    assert len(snapshot(client).json()["decisions"]) == 1
    assert client.get("/api/tasks/" + task_id).json() == before


def test_week_and_subject_validation_and_separate_weeks(setup):
    client, _ = setup
    target = task(client)
    assert snapshot(client, "2026-10-06").status_code == 422
    assert snapshot(client, zone="Unknown/Zone").status_code == 422
    assert decide(client, "TASK", target, week="2026-10-06").status_code == 422
    assert decide(client, "PROJECT", target).status_code == 404
    assert decide(client, "TASK", target).status_code == 200
    assert decide(client, "TASK", target, week="2026-10-12").status_code == 200
    assert len(snapshot(client).json()["decisions"]) == 1
    assert len(snapshot(client, "2026-10-12").json()["decisions"]) == 1
    assert client.post("/api/tasks/" + target + "/transition/complete").status_code == 200
    assert decide(client, "TASK", target, revision=1).status_code == 422


def test_no_interaction_is_not_equated_with_silence_and_old_facts_resurface(setup):
    client, factory = setup
    old_task = task(client, "Older observation")
    unknown_task = task(client, "No instrumented fact")
    with factory() as session:
        events = session.scalars(select(HistoryEventRecord)).all()
        assert events
        for event in events:
            if event.task_id == old_task:
                event.recorded_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
            if event.task_id == unknown_task:
                session.delete(event)
        session.commit()
    result = snapshot(client)
    assert result.status_code == 200, result.text
    value = result.json()
    assert old_task in {t["task_id"] for t in value["no_recent_interaction"]}
    assert unknown_task in {t["task_id"] for t in value["activity_unknown"]}
    assert unknown_task not in {t["task_id"] for t in value["no_recent_interaction"]}
