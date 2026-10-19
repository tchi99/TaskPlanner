"""TP-022B API previews conflict consequences and never moves local bookings."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import (
    AvailabilityExceptionRecord, ConfirmedTimeBlockRecord, HistoryEventRecord,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader


class EmptyCalendar:
    def list_commitments(self, starts_at, ends_at, timezone_name):
        return ()


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_calendar_reader] = lambda: EmptyCalendar()
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def next_monday():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    return today + timedelta(days=(7 - today.weekday()) % 7 + 14)


def local(day, hour):
    return datetime.combine(day, datetime.min.time(), ZoneInfo("America/Toronto")).replace(hour=hour).isoformat()


def test_stale_preview_is_rejected_and_exception_updates_are_versioned(runtime):
    client, factory = runtime
    day = next_monday()
    def proposal(hour):
        return {
            "action": "ADD", "kind": "GENERAL",
            "timezone_name": "America/Toronto",
            "starts_at": local(day, hour), "ends_at": local(day, hour + 1),
        }
    first = proposal(9)
    token = client.post("/api/availability/exceptions/preview", json=first).json()["fingerprint"]
    other = proposal(13)
    fresh = client.post("/api/availability/exceptions/preview", json=other).json()["fingerprint"]
    made = client.post("/api/availability/exceptions", json={
        **other, "expected_fingerprint": fresh,
    })
    assert made.status_code == 201, made.text
    assert client.post("/api/availability/exceptions", json={
        **first, "expected_fingerprint": token,
    }).status_code == 409
    exception_id = made.json()["id"]
    edited = {**other, "exception_id": exception_id, "expected_version": 1,
              "starts_at": local(day, 14), "ends_at": local(day, 15)}
    newer = client.post("/api/availability/exceptions/preview", json=edited)
    assert newer.status_code == 200, newer.text
    changed = client.patch(f"/api/availability/exceptions/{exception_id}", json={
        **edited, "expected_fingerprint": newer.json()["fingerprint"],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert client.patch(f"/api/availability/exceptions/{exception_id}", json={
        **edited, "expected_fingerprint": newer.json()["fingerprint"],
    }).status_code == 409
    assert len(client.get("/api/availability/exceptions").json()) == 1
    with factory() as session:
        events = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_type == "AVAILABILITY_EXCEPTION"
        )).all()
        assert len(events) == 2


def test_local_dst_gap_rejected_and_read_window_bounded(runtime):
    client, _ = runtime
    invalid = {
        "action": "UNAVAILABLE", "timezone_name": "America/Toronto",
        "starts_at": "2027-03-14T02:30:00-05:00",
        "ends_at": "2027-03-14T03:30:00-04:00",
    }
    assert client.post("/api/availability/exceptions/preview", json=invalid).status_code == 422
    start = next_monday()
    assert client.get("/api/availability/effective", params={
        "from": start.isoformat(), "to": (start + timedelta(days=94)).isoformat(),
        "timezone_name": "America/Toronto",
    }).status_code == 422
