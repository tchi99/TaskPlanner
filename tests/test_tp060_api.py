"""Daily selection, deliberate midday changes, close, resurfacing and safety."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app

DAY = "2026-10-10"
ZONE = "America/Toronto"
URL = "/api/review/daily"


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def get(client, day=DAY):
    response = client.get(URL, params={"day": day, "timezone_name": ZONE})
    assert response.status_code == 200, response.text
    return response.json()


def new_task(client, title, *, clarify=True):
    result = client.post("/api/tasks", json={"title": title})
    assert result.status_code == 201, result.text
    task_id = result.json()["id"]
    if clarify:
        assert client.post("/api/tasks/" + task_id + "/clarify", json={}).status_code == 200
    return task_id


def choose(client, ids, revision=0, day=DAY, reason="MORNING", confirmed=True):
    return client.post(URL + "/select", json={
        "day": day, "timezone_name": ZONE, "task_ids": ids,
        "expected_revision": revision, "reason": reason, "confirmed": confirmed,
    })


def close(client, revision, followups, day=DAY, confirmed=True):
    return client.post(URL + "/close", json={
        "day": day, "timezone_name": ZONE, "expected_revision": revision,
        "followups": followups, "confirmed": confirmed,
    })


def test_morning_selection_is_persisted_only_after_confirmation(client):
    protected = new_task(client, "Protected")
    flexible = new_task(client, "Flexible")
    assert client.patch("/api/tasks/" + protected + "/protection",
                        json={"protection": "PROTECTED"}).status_code == 200
    before = client.get("/api/tasks").json()
    assert get(client)["state"] == "NOT_CHOSEN"
    assert get(client)["revision"] == 0
    assert choose(client, [protected], confirmed=False).status_code == 422
    assert get(client)["state"] == "NOT_CHOSEN"
    chosen = choose(client, [protected, flexible])
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["state"] == "OPEN"
    assert chosen.json()["selected_task_ids"] == [protected, flexible]
    assert chosen.json()["revision"] == 1
    assert chosen.json()["calendar_written"] is False
    assert get(client)["selected_task_ids"] == [protected, flexible]
    assert client.get("/api/tasks").json() == before


def test_midday_change_and_stale_or_invalid_selection_are_rejected(client):
    a = new_task(client, "Alpha")
    b = new_task(client, "Beta")
    inbox = new_task(client, "Inbox", clarify=False)
    assert choose(client, [a]).status_code == 200
    assert choose(client, [b], 1, reason="MORNING").status_code == 422
    assert choose(client, [b], 0, reason="SIGNIFICANT_EVENT").status_code == 409
    assert choose(client, [a, a], 1, reason="SIGNIFICANT_EVENT").status_code == 422
    assert choose(client, [inbox], 1, reason="SIGNIFICANT_EVENT").status_code == 422
    assert choose(client, [b], 1, reason="SIGNIFICANT_EVENT", confirmed=False).status_code == 422
    assert choose(client, [b], 1, reason="SIGNIFICANT_EVENT").status_code == 200
    assert get(client)["selected_task_ids"] == [b]
    assert get(client)["revision"] == 2


def test_end_of_day_needs_explicit_followup_dates_and_never_completes_task(client):
    a = new_task(client, "Still open")
    done = new_task(client, "Actually done")
    assert choose(client, [a, done]).status_code == 200
    assert client.post("/api/tasks/" + done + "/transition/complete").status_code == 200
    assert close(client, 1, [], confirmed=False).status_code == 422
    assert close(client, 1, []).status_code == 422
    assert close(client, 1, [{"task_id": a, "review_on": DAY}]).status_code == 422
    result = close(client, 1, [{"task_id": a, "review_on": "2026-10-12"}])
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "CLOSED"
    assert result.json()["revision"] == 2
    assert result.json()["followups"] == [{"task_id": a, "review_on": "2026-10-12"}]
    assert client.get("/api/tasks/" + a).json()["status"] == "TODO"
    assert client.get("/api/tasks/" + done).json()["status"] == "DONE"
    assert close(client, 2, []).status_code == 422
    assert choose(client, [a], 2, reason="SIGNIFICANT_EVENT").status_code == 422
    assert get(client, "2026-10-11")["resurfaced"] == []
    assert [item["task_id"] for item in get(client, "2026-10-12")["resurfaced"]] == [a]
    assert get(client, "2026-10-12")["resurfaced"][0]["reason"] == "REVIEW_DUE"


def test_unfinished_prior_day_reemerges_without_auto_select_or_negative_labels(client):
    a = new_task(client, "Needs a decision")
    assert choose(client, [a], day="2026-10-09").status_code == 200
    view = get(client)
    assert view["state"] == "NOT_CHOSEN"
    assert view["selected_task_ids"] == []
    assert [item["task_id"] for item in view["resurfaced"]] == [a]
    assert view["resurfaced"][0]["reason"] == "UNFINISHED_DAY"
    assert "fault" not in str(view).lower()
    assert choose(client, [a]).status_code == 200
    assert get(client)["resurfaced"] == []


def test_empty_day_timezone_validation_and_no_unconfirmed_side_effects(client):
    assert choose(client, []).status_code == 200
    assert close(client, 1, []).status_code == 200
    assert get(client)["state"] == "CLOSED"
    assert client.get(URL, params={"day": DAY, "timezone_name": "Invalid/Zone"}).status_code == 422
    assert choose(client, [new_task(client, "Later")], 2,
                  reason="SIGNIFICANT_EVENT").status_code == 422
