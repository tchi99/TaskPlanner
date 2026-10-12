"""TP-022C integration: declared vs free, protected/preferred, stale confirmation."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import ConfirmedTimeBlockRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

ZONE = "America/Toronto"


class Reader:
    def __init__(self):
        self.events = []

    def list_commitments(self, start, end, zone):
        assert zone == ZONE
        return tuple(self.events)


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    reader = Reader()
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_calendar_reader] = lambda: reader
    try:
        with TestClient(app) as client:
            yield client, reader, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def monday():
    today = datetime.now(ZoneInfo(ZONE)).date()
    return today + timedelta(days=14 + (7 - today.weekday()) % 7)


def local(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(
        hour=hour, minute=minute,
    ).isoformat()


def rule(client, monday_, kind, begin, end, *, category=None, mode=None):
    payload = {
        "effective_from": monday_.isoformat(), "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": begin, "ends_at_local": end,
        "kind": kind,
    }
    if category:
        payload["work_type_id"] = category
    if mode:
        payload["mode"] = mode
    response = client.post("/api/availability/rules", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def task(client, category, minutes):
    created = client.post("/api/tasks", json={
        "title": "Candidate", "estimated_minutes": minutes,
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert client.post(f"/api/tasks/{task_id}/clarify", json={
        "work_type_id": category,
    }).status_code == 200
    return task_id


def setup_week(client, monday_):
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    admin = client.post("/api/work-types", json={"name": "Admin"}).json()["id"]
    rule(client, monday_, "GENERAL", "09:00", "12:00")
    rule(client, monday_, "CATEGORIZED", "09:00", "10:00",
         category=focus, mode="PROTECTED")
    rule(client, monday_, "CATEGORIZED", "10:00", "11:00",
         category=focus, mode="PREFERRED")
    return focus, admin


def test_protected_never_borrowed_preferred_requires_explicit_acceptance(runtime):
    client, reader, factory = runtime
    week = monday()
    day = week + timedelta(days=1)
    focus, admin = setup_week(client, week)
    task_id = task(client, admin, 60)
    root = f"/api/capacity/weeks/{week.isoformat()}"
    payload = {"task_ids": [task_id], "timezone_name": ZONE}
    declared = client.post(root + "/evaluate", json=payload)
    assert declared.status_code == 200, declared.text
    assert declared.json()["available_minutes"] == 180
    assert declared.json()["status"] == "OVER_CAPACITY"
    planned = client.post(root + "/proposals", json=payload).json()
    assert "REASSIGN_PREFERRED" in [v["kind"] for v in planned["options"]]

    strict = client.post(root + "/time-blocks/preview", json=payload).json()
    assert strict["suggestions"] == []
    assert not strict["can_confirm"]
    offered = {**payload, "offer_transfers": True}
    preview = client.post(root + "/time-blocks/preview", json=offered)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["can_confirm"] and data["requires_transfer_confirmation"]
    assert len(data["suggestions"]) == 1
    suggested = data["suggestions"][0]
    assert suggested["transferred_from"] == focus
    assert suggested["work_type_id"] == admin
    assert suggested["starts_at"] == local(day, 10)
    assert suggested["ends_at"] == local(day, 11)
    confirm = {**offered, "fingerprint": data["fingerprint"], "confirmed": True}
    assert client.post(root + "/time-blocks/confirm", json=confirm).status_code == 422
    result = client.post(root + "/time-blocks/confirm", json={
        **confirm, "accept_transfers": True,
    })
    assert result.status_code == 200, result.text
    assert result.json()["blocks"][0]["transferred_from"] == focus
    assert client.post(root + "/time-blocks/confirm", json={
        **confirm, "accept_transfers": True,
    }).status_code == 409
    with factory() as session:
        rows = session.scalars(select(ConfirmedTimeBlockRecord)).all()
        assert len(rows) == 1
        assert rows[0].transferred_from_work_type_id == focus
    effective = client.get("/api/availability/effective", params={
        "from": week.isoformat(), "to": (week + timedelta(days=7)).isoformat(),
        "timezone_name": ZONE,
    }).json()
    assert not [i for i in effective["issues"] if i["booking_id"]]
    verified = client.get("/api/availability/verified", params={
        "week_start": week.isoformat(), "timezone_name": ZONE,
    })
    assert verified.status_code == 200, verified.text
    assert verified.json()["free_minutes"] == 120
    reader.events.append(CalendarCommitment(
        "primary", "occupied", "Busy", datetime.fromisoformat(local(day, 9)),
        datetime.fromisoformat(local(day, 9, 30)),
    ))
    busy = client.get("/api/availability/verified", params={
        "week_start": week.isoformat(), "timezone_name": ZONE,
    }).json()
    assert busy["calendar_checked"]
    assert busy["free_minutes"] == 90


def test_availability_change_invalidates_preview_and_keeps_bookings(runtime):
    client, reader, factory = runtime
    week = monday()
    day = week + timedelta(days=1)
    focus, _ = setup_week(client, week)
    task_id = task(client, focus, 60)
    root = f"/api/capacity/weeks/{week.isoformat()}"
    body = {"task_ids": [task_id], "timezone_name": ZONE}
    original = client.post(root + "/time-blocks/preview", json=body).json()
    assert original["can_confirm"]
    exception = {
        "action": "UNAVAILABLE", "timezone_name": ZONE,
        "starts_at": local(day, 9), "ends_at": local(day, 10),
    }
    snapshot = client.post("/api/availability/exceptions/preview", json=exception)
    assert snapshot.status_code == 200, snapshot.text
    assert client.post("/api/availability/exceptions", json={
        **exception, "expected_fingerprint": snapshot.json()["fingerprint"],
    }).status_code == 201
    assert client.post(root + "/time-blocks/confirm", json={
        **body, "fingerprint": original["fingerprint"], "confirmed": True,
    }).status_code == 409
    assert client.get(root + "/time-blocks").json() == []
    current = client.post(root + "/time-blocks/preview", json=body).json()
    assert current["suggestions"][0]["starts_at"] == local(day, 10)
    assert current["fingerprint"] != original["fingerprint"]


def test_google_calendar_checked_before_new_confirmation(runtime):
    client, reader, factory = runtime
    week = monday()
    day = week + timedelta(days=1)
    focus, _ = setup_week(client, week)
    task_id = task(client, focus, 60)
    root = f"/api/capacity/weeks/{week.isoformat()}"
    body = {"task_ids": [task_id], "timezone_name": ZONE}
    previous = client.post(root + "/time-blocks/preview", json=body).json()
    reader.events.append(CalendarCommitment(
        "primary", "meeting", "Meeting",
        datetime.fromisoformat(local(day, 9)),
        datetime.fromisoformat(local(day, 10)),
    ))
    confirm = client.post(root + "/time-blocks/confirm", json={
        **body, "fingerprint": previous["fingerprint"], "confirmed": True,
    })
    assert confirm.status_code == 409
    assert client.get(root + "/time-blocks").json() == []
