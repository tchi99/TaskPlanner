"""TP-026A regression replacements for superseded manual/exclusive availability APIs.

ADR-0025 requires permanent real parents, one physical envelope, overlapping
typed permissions, explicit confirmations and no implicit NULL booking. These
tests replace outdated TP-020/022/023/030/031/040/041/051 assumptions; the
other modern TP-024/025/026 integration and migration tests remain enabled.
"""
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import (
    AvailabilityBlockRecord, ConfirmedTimeBlockRecord, HistoryEventRecord,
    RecurringAvailabilityRevisionRecord,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

ZONE = "America/Toronto"
WEEK = date(2027, 1, 4)
DAY = date(2027, 1, 5)
BASE = f"/api/capacity/weeks/{WEEK}/time-blocks"
GRID = "/api/availability/weekly-schedule"
EDIT = "/api/availability/eligibility-edits"


class Reader:
    def __init__(self):
        self.events = []
        self.calls = 0

    def list_commitments(self, start, end, zone):
        assert zone == ZONE
        self.calls += 1
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
            yield client, reader, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def local(hour, minute=0):
    return datetime(2027, 1, 5, hour, minute,
                    tzinfo=ZoneInfo(ZONE)).isoformat()


def configure(client, *, permissions=True):
    parent = client.post("/api/schedule-scopes", json={"name": "Travail"})
    assert parent.status_code == 201, parent.text
    scope = parent.json()["id"]
    types = []
    for name in ("Focus", "Reunions"):
        response = client.post("/api/work-types", json={
            "name": name, "scope_id": scope,
        })
        assert response.status_code == 201, response.text
        types.append(response.json()["id"])
    body = {
        "effective_from": WEEK.isoformat(), "timezone_name": ZONE,
        "sections": [{"weekday": 1, "kind": "GENERAL", "scope_id": scope,
                      "work_type_id": None,
                      "slots": [{"starts_at_local": "10:00",
                                 "ends_at_local": "12:00"}]}],
        "expected_versions": {},
    }
    first = client.post(GRID + "/preview", json=body)
    assert first.status_code == 200, first.text
    saved = client.post(GRID + "/confirm", json={
        **body, "fingerprint": first.json()["fingerprint"],
        "command_id": str(uuid4()), "confirmed": True,
    })
    assert saved.status_code == 200, saved.text
    receipts = []
    if permissions:
        for typ, rank in zip(types, (1, 2)):
            receipts.append(permission(client, scope, typ, rank=rank))
    return scope, types, receipts


def permission(client, scope, typ, *, rank, series_id=None, expected_version=0):
    body = {
        "draft_id": str(uuid4()), "series_id": series_id,
        "legacy_rule_id": None, "scope_id": scope, "work_type_id": typ,
        "expected_version": expected_version, "expected_legacy_version": None,
        "effective_from": DAY.isoformat(), "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": "10:00",
        "ends_at_local": "12:00", "priority_rank": rank,
        "enabled": True, "start_fold": None, "end_fold": None,
    }
    preview = client.post(EDIT + "/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["blocking_issues"] == []
    response = client.post(EDIT + "/confirm", json={
        **body, "fingerprint": preview.json()["fingerprint"],
        "command_id": str(uuid4()), "confirmed": True,
        "acknowledge_bookings": False,
    })
    assert response.status_code == 200, response.text
    return response.json()


def task(client, typ=None, minutes=60, protection=None):
    created = client.post("/api/tasks", json={
        "title": "Work unit", "estimated_minutes": minutes,
    })
    assert created.status_code == 201, created.text
    ident = created.json()["id"]
    clarified = client.post(f"/api/tasks/{ident}/clarify",
                            json={"work_type_id": typ} if typ else {})
    assert clarified.status_code == 200, clarified.text
    if protection:
        applied = client.patch(f"/api/tasks/{ident}/protection", json={
            "protection": protection, "confirm_downgrade": protection == "FLEXIBLE",
        })
        assert applied.status_code == 200, applied.text
    return ident


def preview(client, ids, fixed=()):
    result = client.post(BASE + "/preview", json={
        "task_ids": list(ids), "timezone_name": ZONE,
        "fixed_slots": list(fixed),
    })
    assert result.status_code == 200, result.text
    return result.json()


def confirm(client, ids, offer, *, command=None, fixed=()):
    return client.post(BASE + "/confirm", json={
        "task_ids": list(ids), "timezone_name": ZONE,
        "fixed_slots": list(fixed), "fingerprint": offer["fingerprint"],
        "confirmed": True, "command_id": str(command or uuid4()),
    })


def test_legacy_manual_writes_are_rejected_without_side_effects(runtime):
    client, _, factory = runtime
    response = client.post(f"/api/capacity/weeks/{WEEK}/blocks", json={
        "starts_at": local(10), "ends_at": local(11),
    })
    assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            AvailabilityBlockRecord)) == 0


def test_exclusive_recurring_writes_are_rejected_without_revisions(runtime):
    client, _, factory = runtime
    scope, types, _ = configure(client, permissions=False)
    body = {"effective_from": WEEK.isoformat(), "timezone_name": ZONE,
            "days_of_week": [1], "starts_at_local": "10:00",
            "ends_at_local": "12:00"}
    for extra in ({"kind": "GENERAL"}, {
        "kind": "CATEGORIZED", "work_type_id": types[0], "mode": "PREFERRED",
    }):
        result = client.post("/api/availability/rules", json={**body, **extra})
        assert result.status_code == 422, result.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            RecurringAvailabilityRevisionRecord)) == 1  # legitimate parent envelope


def test_physical_envelope_without_permissions_never_grants_booking(runtime):
    client, _, _ = runtime
    _, types, _ = configure(client, permissions=False)
    chosen = task(client, types[0], 60)
    offer = preview(client, [chosen])
    assert not offer["can_confirm"]
    assert not offer["suggestions"]


def test_eligible_overlaps_do_not_double_physical_capacity(runtime):
    client, _, _ = runtime
    _, types, _ = configure(client)
    week = client.get("/api/availability/eligibility-week", params={
        "week_start": WEEK.isoformat(), "timezone_name": ZONE,
    })
    assert week.status_code == 200, week.text
    data = week.json()
    assert data["physical_minutes"] == 120
    assert sorted(x["minutes"] for x in data["potential_minutes"]) == [120, 120]
    assert any(len(fragment["choices"]) == 2 for fragment in data["fragments"])
    first = task(client, types[0], 90)
    second = task(client, types[1], 90)
    evaluation = client.post(f"/api/capacity/weeks/{WEEK}/evaluate", json={
        "task_ids": [first, second], "timezone_name": ZONE,
    })
    assert evaluation.status_code == 200, evaluation.text
    assert evaluation.json()["available_minutes"] == 120
    assert evaluation.json()["known_demand_minutes"] == 180
    assert evaluation.json()["status"] == "OVER_CAPACITY"


def test_unclassified_capture_cannot_consume_null_capacity(runtime):
    client, _, factory = runtime
    configure(client)
    unclassified = task(client)
    response = preview(client, [unclassified])
    assert response["suggestions"] == []
    assert response["unplaced"][0]["reason"] == "UNCLASSIFIED_WORK_TYPE"
    assert response["can_confirm"] is False
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            ConfirmedTimeBlockRecord)) == 0


def test_contextual_priority_and_meeting_fallback(runtime):
    client, _, _ = runtime
    _, types, _ = configure(client)
    meeting = task(client, types[1], 120)
    focus = task(client, types[0], 120)
    together = preview(client, [meeting, focus])
    assert {x["task_id"] for x in together["suggestions"]} == {focus}
    assert together["suggestions"][0]["priority_rank"] == 1
    alone = preview(client, [meeting])
    assert alone["can_confirm"]
    assert alone["suggestions"][0]["work_type_id"] == types[1]


def test_confirmed_booking_is_idempotent_and_prevents_duplicate(runtime):
    client, reader, factory = runtime
    _, types, _ = configure(client)
    chosen = task(client, types[1], 120)
    other = task(client, types[0], 120)
    fixed = [{"task_id": chosen, "starts_at": local(10),
              "ends_at": local(12)}]
    original = preview(client, [chosen], fixed)
    assert original["can_confirm"]
    command = uuid4()
    first = confirm(client, [chosen], original, command=command, fixed=fixed)
    assert first.status_code == 200, first.text
    read_count = reader.calls
    replay = confirm(client, [chosen], original, command=command, fixed=fixed)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert reader.calls == read_count
    assert not preview(client, [other])["can_confirm"]
    assert confirm(client, [chosen], original, fixed=fixed).status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            ConfirmedTimeBlockRecord)) == 1
        assert session.scalar(select(func.count()).select_from(
            HistoryEventRecord).where(
                HistoryEventRecord.event_type == "TIME_BLOCK_CONFIRMED")) == 1


def test_priority_revision_makes_old_confirmation_stale(runtime):
    client, _, factory = runtime
    scope, types, receipts = configure(client)
    candidate = task(client, types[0], 60)
    original = preview(client, [candidate])
    assert original["can_confirm"]
    permission(client, scope, types[0], rank=3,
               series_id=receipts[0]["series_id"], expected_version=1)
    stale = confirm(client, [candidate], original)
    assert stale.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            ConfirmedTimeBlockRecord)) == 0


def test_google_busy_blocks_whole_fixed_admission(runtime):
    client, reader, _ = runtime
    _, types, _ = configure(client)
    chosen = task(client, types[1], 120)
    reader.events.append(CalendarCommitment(
        "primary", "busy", "Busy",
        datetime.fromisoformat(local(10, 30)),
        datetime.fromisoformat(local(10, 45)),
    ))
    fixed = [{"task_id": chosen, "starts_at": local(10),
              "ends_at": local(12)}]
    result = preview(client, [chosen], fixed)
    assert not result["can_confirm"]
    assert not result["suggestions"]
    assert result["unplaced"][0]["reason"] == "FIXED_SLOT_NOT_VERIFIED_FREE_OR_ADMISSIBLE"


def test_weekly_proposals_are_read_only_for_protected_tasks(runtime):
    client, _, factory = runtime
    _, types, _ = configure(client)
    must = task(client, types[0], 90, "PROTECTED")
    may = task(client, types[1], 90, "FLEXIBLE")
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(
            HistoryEventRecord))
    result = client.post(f"/api/capacity/weeks/{WEEK}/proposals", json={
        "task_ids": [must, may], "timezone_name": ZONE,
    })
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "PROPOSED"
    assert result.json()["baseline"]["known_demand_minutes"] == 180
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            HistoryEventRecord)) == before


def test_morning_and_calendar_reads_do_not_mutate_tasks_or_capacity(runtime):
    client, reader, _ = runtime
    _, types, _ = configure(client)
    ident = task(client, types[0], 60, "PROTECTED")
    task_before = client.get(f"/api/tasks/{ident}").json()
    week_before = client.get(f"/api/capacity/weeks/{WEEK}").json()
    morning = client.get(f"/api/review/morning?day={DAY}&timezone_name={ZONE}")
    assert morning.status_code == 200, morning.text
    assert morning.json()["is_hypothetical"] is True
    calendar = client.get(f"/api/capacity/weeks/{WEEK}/calendar", params={
        "timezone_name": ZONE,
    })
    assert calendar.status_code == 200, calendar.text
    assert calendar.json()["is_read_only"] is True
    assert reader.calls >= 1
    assert client.get(f"/api/tasks/{ident}").json() == task_before
    assert client.get(f"/api/capacity/weeks/{WEEK}").json() == week_before
