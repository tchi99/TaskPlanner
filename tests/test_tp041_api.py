"""TP-041: preview/revalidate/confirm is local, explicit and fail-closed."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarUnavailable,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

WEEK = "/api/capacity/weeks/2026-10-05"
BASE = WEEK + "/time-blocks"


class Reader:
    def __init__(self):
        self.events = []
        self.calls = 0

    def list_commitments(self, starts_at, ends_at, timezone_name):
        self.calls += 1
        assert timezone_name == "America/Toronto"
        return tuple(self.events)


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    reader = Reader()
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_calendar_reader] = lambda: reader
    try:
        with TestClient(app) as client:
            yield client, reader
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def task(client, estimated=60):
    task_id = client.post("/api/tasks", json={
        "title": "Task", "estimated_minutes": estimated,
    }).json()["id"]
    assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    return task_id


def manual(client):
    resp = client.post(WEEK + "/blocks", json={
        "starts_at": "2026-10-05T09:00:00-04:00",
        "ends_at": "2026-10-05T11:00:00-04:00",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def payload(ids):
    return {"task_ids": ids, "timezone_name": "America/Toronto"}


def test_preview_is_pure_confirmation_is_explicit_and_revalidation_blocks_replay(runtime):
    client, reader = runtime
    block_id = manual(client)
    task_id = task(client, 60)
    before = client.get(WEEK).json()
    proposed = client.post(BASE + "/preview", json=payload([task_id]))
    assert proposed.status_code == 200, proposed.text
    preview = proposed.json()
    assert preview["can_confirm"] is True
    assert preview["calendar_checked"] is True
    assert preview["destinations"] == "TASKPLANNER_LOCAL_ONLY"
    assert preview["suggestions"][0]["minutes"] == 60
    assert client.get(BASE).json() == []
    assert client.get(WEEK).json() == before
    confirm = {**payload([task_id]), "fingerprint": preview["fingerprint"],
               "confirmed": True}
    assert client.post(BASE + "/confirm", json={**confirm, "confirmed": False}).status_code == 422
    assert client.get(BASE).json() == []
    response = client.post(BASE + "/confirm", json=confirm)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "CONFIRMED_LOCAL"
    assert response.json()["calendar_written"] is False
    assert len(client.get(BASE).json()) == 1
    assert reader.calls == 2
    assert client.post(BASE + "/confirm", json=confirm).status_code == 409
    assert client.delete(WEEK + "/blocks/" + block_id).status_code == 422
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "TODO"


def test_external_calendar_conflict_makes_preview_stale_and_respects_commitments(runtime):
    client, reader = runtime
    manual(client)
    task_id = task(client)
    preview = client.post(BASE + "/preview", json=payload([task_id])).json()
    reader.events = [CalendarCommitment(
        "primary", "new", "New meeting",
        datetime.fromisoformat("2026-10-05T09:00:00-04:00"),
        datetime.fromisoformat("2026-10-05T10:00:00-04:00"),
    )]
    response = client.post(BASE + "/confirm", json={
        **payload([task_id]), "fingerprint": preview["fingerprint"],
        "confirmed": True,
    })
    assert response.status_code == 409
    assert client.get(BASE).json() == []
    updated = client.post(BASE + "/preview", json=payload([task_id])).json()
    assert updated["suggestions"][0]["starts_at"] == "2026-10-05T10:00:00-04:00"
    assert client.post(BASE + "/confirm", json={
        **payload([task_id]), "fingerprint": updated["fingerprint"], "confirmed": True,
    }).status_code == 200


def test_incomplete_or_invalid_selection_never_persists(runtime):
    client, _ = runtime
    manual(client)
    unknown = task(client, None)
    response = client.post(BASE + "/preview", json=payload([unknown]))
    assert response.status_code == 200
    assert response.json()["unplaced"][0]["reason"] == "ESTIMATE_UNKNOWN"
    assert response.json()["can_confirm"] is False
    assert client.post(BASE + "/confirm", json={
        **payload([unknown]), "confirmed": True,
        "fingerprint": response.json()["fingerprint"],
    }).status_code == 422
    assert client.post(BASE + "/preview", json=payload([])).status_code == 422
    assert client.post(BASE + "/preview", json=payload([unknown, unknown])).status_code == 422
    assert client.post("/api/capacity/weeks/2026-10-06/time-blocks/preview",
                       json=payload([unknown])).status_code == 422
    assert client.get(BASE).json() == []


def test_calendar_failure_is_not_treated_as_free_time(runtime):
    client, reader = runtime
    manual(client)
    task_id = task(client)
    class Unavailable:
        def list_commitments(self, *args):
            raise GoogleCalendarUnavailable("secret")
    app.dependency_overrides[get_calendar_reader] = lambda: Unavailable()
    resp = client.post(BASE + "/preview", json=payload([task_id]))
    assert resp.status_code == 502
    assert "secret" not in resp.text
    class Missing:
        def list_commitments(self, *args):
            raise GoogleCalendarNotConfigured()
    app.dependency_overrides[get_calendar_reader] = lambda: Missing()
    assert client.post(BASE + "/preview", json=payload([task_id])).status_code == 503
    assert client.get(BASE).json() == []
