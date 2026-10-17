"""TP-022R: conflict resolution is explicit, idempotent, local and audited."""
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import ConfirmedTimeBlockRecord, HistoryEventRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

ZONE = "America/Toronto"


class Calendar:
    def __init__(self):
        self.events = []
        self.fail = False

    def list_commitments(self, start, end, zone):
        assert zone == ZONE
        if self.fail:
            from app.infrastructure.google_calendar import GoogleCalendarUnavailable
            raise GoogleCalendarUnavailable("not public")
        return tuple(self.events)


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    calendar = Calendar()
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_calendar_reader] = lambda: calendar
    try:
        with TestClient(app) as client:
            yield client, calendar, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def week():
    today = datetime.now(ZoneInfo(ZONE)).date()
    return today + timedelta(days=14 + (7 - today.weekday()) % 7)


def clock(day, hour):
    return datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(
        hour=hour,
    ).isoformat()


def create_booking(client, monday):
    day = monday + timedelta(days=1)
    root = f"/api/capacity/weeks/{monday}"
    for begin, end in ((9, 10), (10, 11)):
        response = client.post(root + "/blocks", json={
            "starts_at": clock(day, begin), "ends_at": clock(day, end),
        })
        assert response.status_code == 201, response.text
    task = client.post("/api/tasks", json={
        "title": "Must be kept", "estimated_minutes": 60,
    }).json()["id"]
    assert client.post(f"/api/tasks/{task}/clarify", json={}).status_code == 200
    base = root + "/time-blocks"
    body = {"task_ids": [task], "timezone_name": ZONE}
    preview = client.post(base + "/preview", json=body)
    assert preview.status_code == 200, preview.text
    committed = client.post(base + "/confirm", json={
        **body, "fingerprint": preview.json()["fingerprint"], "confirmed": True,
    })
    assert committed.status_code == 200, committed.text
    booking = committed.json()["blocks"][0]
    assert booking["revision"] == 1
    return base, task, booking, day


def unavailability(client, day):
    values = {
        "action": "UNAVAILABLE", "timezone_name": ZONE,
        "starts_at": clock(day, 9), "ends_at": clock(day, 10),
        "reason": "Unexpected appointment",
    }
    preview = client.post("/api/availability/exceptions/preview", json=values)
    assert preview.status_code == 200, preview.text
    assert any(v["booking_id"] for v in preview.json()["issues"])
    result = client.post("/api/availability/exceptions", json={
        **values, "expected_fingerprint": preview.json()["fingerprint"],
        "acknowledge_conflicts": True,
    })
    assert result.status_code == 201, result.text


def path(base, booking):
    return base + "/" + booking["id"] + "/resolution"


def snapshot(client, url, decision, revision=1, **kwargs):
    request = {"decision": decision, "expected_revision": revision,
               "timezone_name": ZONE, "reason": "Reviewed explicitly", **kwargs}
    preview = client.post(url + "/preview", json=request)
    assert preview.status_code == 200, preview.text
    return request, preview.json()


def apply(client, url, request, preview, *, decision_id=None):
    return client.post(url + "/confirm", json={
        "confirmed": True, **request, "fingerprint": preview["fingerprint"],
        "decision_id": str(decision_id or uuid4()),
    })


def test_keep_conflict_then_cancel_is_confirmed_audited_and_idempotent(runtime):
    client, calendar, factory = runtime
    monday = week()
    base, task, booking, day = create_booking(client, monday)
    unavailability(client, day)
    url = path(base, booking)
    retained, token = snapshot(client, url, "KEEP")
    assert "BOOKING_OUTSIDE_EFFECTIVE_AVAILABILITY" in token["conflict_codes"]
    assert token["state"] == "PROPOSED"
    assert client.get(base).json()[0]["revision"] == 1
    choice = uuid4()
    response = apply(client, url, retained, token, decision_id=choice)
    assert response.status_code == 200, response.text
    assert response.json()["booking"]["revision"] == 2
    assert response.json()["booking"]["status"] == "CONFIRMED"
    assert client.get(base).json()[0]["id"] == booking["id"]
    replay = apply(client, url, retained, token, decision_id=choice)
    assert replay.status_code == 200, replay.text
    assert replay.json()["decision_id"] == str(choice)
    assert apply(client, url, retained, token).status_code == 409
    history = client.get(url + "/history").json()
    assert len(history) == 1
    assert history[0]["event_type"] == "BOOKING_CONFLICT_RETAINED"
    with factory() as session:
        events = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_type == "TIME_BLOCK",
        ).order_by(HistoryEventRecord.sequence)).all()
        assert [event.event_type for event in events] == [
            "TIME_BLOCK_CONFIRMED", "BOOKING_CONFLICT_RETAINED",
        ]
    cancel, preview = snapshot(client, url, "CANCEL", revision=2)
    assert apply(client, url, {**cancel, "confirmed": False}, preview).status_code == 422
    removed = apply(client, url, cancel, preview)
    assert removed.status_code == 200, removed.text
    assert removed.json()["booking"]["status"] == "CANCELLED"
    assert client.get(base).json() == []
    effective = client.get("/api/availability/effective", params={
        "from": str(monday), "to": str(monday + timedelta(days=7)),
        "timezone_name": ZONE,
    }).json()
    assert not any(v["booking_id"] for v in effective["issues"])
    assert client.get(f"/api/tasks/{task}").json()["status"] == "TODO"
    assert [v["event_type"] for v in client.get(url + "/history").json()] == [
        "BOOKING_CONFLICT_RETAINED", "BOOKING_CANCELLED",
    ]
    with factory() as session:
        row = session.get(ConfirmedTimeBlockRecord, booking["id"])
        assert row.status == "CANCELLED" and row.revision == 3


def test_move_preserves_booking_provenance_and_recomputes_free_time(runtime):
    client, calendar, factory = runtime
    monday = week()
    base, task, booking, day = create_booking(client, monday)
    unavailability(client, day)
    url = path(base, booking)
    request, preview = snapshot(
        client, url, "MOVE", starts_at=clock(day, 10), ends_at=clock(day, 11),
    )
    assert preview["calendar_checked"]
    result = apply(client, url, request, preview)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["calendar_written"] is False
    assert data["booking"]["status"] == "SUPERSEDED"
    assert data["replacement"]["id"] != booking["id"]
    assert data["replacement"]["starts_at"] == clock(day, 10)
    assert [v["id"] for v in client.get(base).json()] == [data["replacement"]["id"]]
    assert client.get(url + "/history").json()[0]["event_type"] == "BOOKING_MOVED"
    assert client.get("/api/availability/verified", params={
        "week_start": str(monday), "timezone_name": ZONE,
    }).json()["free_minutes"] == 0
    with factory() as session:
        rows = session.scalars(select(ConfirmedTimeBlockRecord)).all()
        assert len(rows) == 2
        assert {r.status for r in rows} == {"SUPERSEDED", "CONFIRMED"}


def test_stale_preview_and_calendar_conflict_never_mutate_booking(runtime):
    client, calendar, factory = runtime
    monday = week()
    base, task, booking, day = create_booking(client, monday)
    unavailability(client, day)
    url = path(base, booking)
    request, preview = snapshot(
        client, url, "MOVE", starts_at=clock(day, 10), ends_at=clock(day, 11),
    )
    calendar.events.append(CalendarCommitment(
        "primary", "new", "Busy",
        datetime.fromisoformat(clock(day, 10)),
        datetime.fromisoformat(clock(day, 11)),
    ))
    assert apply(client, url, request, preview).status_code == 409
    assert client.get(base).json()[0]["id"] == booking["id"]
    assert client.post(url + "/preview", json=request).status_code == 422
    calendar.fail = True
    assert client.post(url + "/preview", json=request).status_code == 502
    assert apply(client, url, request, preview).status_code == 502
    # Cancel needs no external calendar read, and must remain possible offline.
    cancel, token = snapshot(client, url, "CANCEL")
    assert token["calendar_checked"] is False
    assert apply(client, url, cancel, token).status_code == 200
    assert client.get(base).json() == []


def test_competing_confirmations_are_serialized_and_one_wins(runtime):
    client, calendar, factory = runtime
    monday = week()
    base, task, booking, day = create_booking(client, monday)
    unavailability(client, day)
    url = path(base, booking)
    keep, keep_preview = snapshot(client, url, "KEEP")
    cancel, cancel_preview = snapshot(client, url, "CANCEL")
    assert apply(client, url, cancel, cancel_preview).status_code == 200
    assert apply(client, url, keep, keep_preview).status_code == 409
    assert client.get(base).json() == []
    with factory() as session:
        rows = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_type == "TIME_BLOCK",
        ).order_by(HistoryEventRecord.sequence)).all()
        assert [event.event_type for event in rows] == [
            "TIME_BLOCK_CONFIRMED", "BOOKING_CANCELLED",
        ]
