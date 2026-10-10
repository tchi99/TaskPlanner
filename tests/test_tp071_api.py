"""TP-071: real HTTP/persistence, history atomicity and descriptive uncertainty."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.work_sessions import change_session, start_session
from app.domain.work_sessions import SessionConflict
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, WorkSessionRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


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


def create_task(client, *, estimate=30):
    response = client.post("/api/tasks", json={"title": "Travail à mesurer",
                                                "estimated_minutes": estimate})
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    return task_id


def test_http_start_pause_resume_finish_and_revision(setup):
    client, factory = setup
    task_id = create_task(client)
    started = client.post(f"/api/tasks/{task_id}/work-sessions", json={
        "planned_minutes": 15,
    })
    assert started.status_code == 201, started.text
    session = started.json()
    assert session["status"] == "ACTIVE"
    assert session["revision"] == 1
    assert session["estimated_minutes"] == 30
    assert client.post(f"/api/tasks/{task_id}/work-sessions", json={}).status_code == 409
    paused = client.post(f"/api/work-sessions/{session['id']}/pause", json={
        "expected_revision": session["revision"], "reason_code": "INTERRUPTION",
    })
    assert paused.status_code == 200, paused.text
    snapshot = paused.json()
    assert snapshot["status"] == "PAUSED"
    assert snapshot["interruptions"] == 1
    assert client.post(f"/api/work-sessions/{session['id']}/resume",
                       json={"expected_revision": 1}).status_code == 409
    resumed = client.post(f"/api/work-sessions/{session['id']}/resume",
                          json={"expected_revision": 2})
    assert resumed.status_code == 200, resumed.text
    finished = client.post(f"/api/work-sessions/{session['id']}/finish",
                           json={"expected_revision": 3})
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "FINISHED"
    assert finished.json()["interruptions"] == 1
    assert client.post(f"/api/work-sessions/{session['id']}/finish",
                       json={"expected_revision": 4}).status_code == 409
    observation = client.get(f"/api/tasks/{task_id}/work-sessions").json()
    assert len(observation["sessions"]) == 1
    assert observation["coverage"] == "UNVERIFIED"
    assert observation["estimate_minutes"] == 30
    assert observation["has_open_sessions"] is False
    assert client.get(f"/api/tasks/{task_id}/detail").json()["status"] == "TODO"
    with factory() as session_db:
        rows = session_db.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.event_type.like("WORK_SESSION_%")
        ).order_by(HistoryEventRecord.sequence)).all()
        assert [r.event_type for r in rows] == [
            "WORK_SESSION_STARTED", "WORK_SESSION_PAUSED",
            "WORK_SESSION_RESUMED", "WORK_SESSION_FINISHED",
        ]
        assert all("title" not in r.payload and "notes" not in r.payload for r in rows)
        assert rows[1].reason_code == "INTERRUPTION"
        assert len(session_db.scalars(select(WorkSessionRecord)).all()) == 1


def test_paused_interval_persists_and_stale_mutation_is_atomic(setup):
    client, factory = setup
    task_id = create_task(client)
    at = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)
    session = start_session(SqlAlchemyUnitOfWork(factory), __import__("uuid").UUID(task_id), now=at)
    paused = change_session(SqlAlchemyUnitOfWork(factory), session.id,
                            action="pause", expected_revision=1,
                            now=at + timedelta(minutes=9))
    assert paused.active_seconds == 540
    with pytest.raises(SessionConflict):
        change_session(SqlAlchemyUnitOfWork(factory), session.id,
                       action="finish", expected_revision=1,
                       now=at + timedelta(hours=5))
    resumed = change_session(SqlAlchemyUnitOfWork(factory), session.id,
                             action="resume", expected_revision=2,
                             now=at + timedelta(hours=5))
    finished = change_session(SqlAlchemyUnitOfWork(factory), session.id,
                              action="finish", expected_revision=3,
                              now=at + timedelta(hours=5, minutes=6))
    assert resumed.active_seconds == 540
    assert finished.active_seconds == 900
    with factory() as db:
        db_session = db.get(WorkSessionRecord, str(session.id))
        assert db_session.active_seconds == 900
        assert db_session.revision == 4
        events = db.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.event_type.like("WORK_SESSION_%")
        )).all()
        assert len(events) == 4


def test_no_work_session_for_inbox_or_wrong_segment(setup):
    client, factory = setup
    task_id = create_task(client)
    segment = client.post(f"/api/tasks/{task_id}/segments", json={
        "title": "Première action", "estimated_minutes": 12,
    })
    assert segment.status_code == 201
    segment_id = segment.json()["segments"][0]["id"]
    assert client.post(f"/api/tasks/{task_id}/work-sessions", json={}).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/work-sessions", json={
        "segment_id": "00000000-0000-0000-0000-000000000001",
    }).status_code == 422
    created = client.post(f"/api/tasks/{task_id}/work-sessions",
                          json={"segment_id": segment_id})
    assert created.status_code == 201, created.text
    assert created.json()["segment_id"] == segment_id


def test_stats_with_insufficient_samples_and_unknown_coverage(setup):
    client, factory = setup
    task_id = create_task(client)
    session = client.post(f"/api/tasks/{task_id}/work-sessions", json={}).json()
    assert client.post(f"/api/work-sessions/{session['id']}/finish",
                       json={"expected_revision": 1}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/transition/complete").status_code == 200
    result = client.get("/api/work-sessions/stats")
    assert result.status_code == 200, result.text
    row = result.json()[0]
    assert row["finished_sessions"] == 1
    assert row["completed_unit_samples"] == 1
    assert row["calibration_ready"] is False
    assert row["median_estimated_minutes"] is None
    assert row["coverage"] == "UNVERIFIED"
    for _ in range(2):
        other = create_task(client)
        started = client.post(f"/api/tasks/{other}/work-sessions", json={}).json()
        client.post(f"/api/work-sessions/{started['id']}/finish",
                    json={"expected_revision": 1})
        client.post(f"/api/tasks/{other}/transition/complete")
    calibrated = client.get("/api/work-sessions/stats").json()[0]
    assert calibrated["completed_unit_samples"] == 3
    assert calibrated["calibration_ready"] is True
    assert calibrated["median_estimated_minutes"] == 30
    assert len(calibrated["deviations_minutes"]) == 3
    assert calibrated["coverage"] == "UNVERIFIED"
