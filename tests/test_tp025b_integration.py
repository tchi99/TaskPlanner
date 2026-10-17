"""TP-025B integration: one physical capacity, priority, fixed bookings and replay."""
from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.domain.eligibility import EligibilityRevision, EligibilitySeries
from app.domain.schedule_scopes import compatibility_scope_id
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import ConfirmedTimeBlockRecord, HistoryEventRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

OWNER = "urn:taskplanner:local"
ZONE = "America/Toronto"
WEEK = date(2027, 1, 4)
DAY = date(2027, 1, 5)
BASE = f"/api/capacity/weeks/{WEEK}/time-blocks"


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


def local(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute,
                    tzinfo=ZoneInfo(ZONE)).isoformat()


def work_type(client, title):
    response = client.post("/api/work-types", json={"name": title})
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def task(client, work_type_id, minutes):
    response = client.post("/api/tasks", json={
        "title": "Work unit", "estimated_minutes": minutes})
    assert response.status_code == 201, response.text
    ident = response.json()["id"]
    response = client.post(f"/api/tasks/{ident}/clarify",
                           json={"work_type_id": str(work_type_id)})
    assert response.status_code == 200, response.text
    return ident


def configure(client, factory, *, include_wednesday=False):
    scope = compatibility_scope_id(OWNER)
    focus, meetings = work_type(client, "Focus"), work_type(client, "Meetings")
    response = client.post("/api/availability/rules", json={
        "effective_from": WEEK.isoformat(), "timezone_name": ZONE,
        "days_of_week": [1, 2] if include_wednesday else [1],
        "starts_at_local": "10:00", "ends_at_local": "11:00",
        "kind": "GENERAL",
    })
    assert response.status_code == 201, response.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.schedule_scopes.ensure_compatibility(OWNER)
        series = []
        for target, rank in ((focus, 1), (meetings, 2)):
            sid = uuid4()
            rev = EligibilityRevision(
                sid, 1, WEEK, None, ZONE, (1,),
                "10:00", "11:00", priority_rank=rank,
            )
            value = EligibilitySeries(sid, OWNER, scope, target, 1, (rev,))
            uow.eligibility.add(value)
            series.append(value)
        if include_wednesday:
            for target in (focus, meetings):
                sid = uuid4()
                rev = EligibilityRevision(
                    sid, 1, WEEK, None, ZONE, (2,),
                    "10:00", "11:00", priority_rank=None,
                )
                uow.eligibility.add(
                    EligibilitySeries(sid, OWNER, scope, target, 1, (rev,)))
        uow.commit()
    return focus, meetings, series


def preview(client, ids, *, fixed=()):
    response = client.post(BASE + "/preview", json={
        "task_ids": ids, "timezone_name": ZONE, "fixed_slots": list(fixed)})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, ids, proposal, *, command=None, fixed=()):
    return client.post(BASE + "/confirm", json={
        "task_ids": ids, "timezone_name": ZONE, "fixed_slots": list(fixed),
        "fingerprint": proposal["fingerprint"], "confirmed": True,
        "command_id": str(command or uuid4()),
    })


def test_contextual_priority_beats_order_but_meeting_alone_uses_free_minutes(runtime):
    client, _, _ = runtime
    focus, meetings, _ = configure(client, runtime[2])
    meeting_id, focus_id = task(client, meetings, 60), task(client, focus, 60)
    joint = preview(client, [meeting_id, focus_id])
    assert {s["task_id"] for s in joint["suggestions"]} == {focus_id}
    assert joint["suggestions"][0]["priority_rank"] == 1
    assert joint["suggestions"][0]["placement_reason"] == "CONTEXTUAL_PRIORITY"
    assert joint["suggestions"][0]["transferred_from"] is None
    assert not joint["can_confirm"]
    alone = preview(client, [meeting_id])
    assert alone["can_confirm"]
    assert alone["suggestions"][0]["work_type_id"] == str(meetings)
    assert not alone["requires_transfer_confirmation"]
    assert alone["suggestions"][0]["starts_at"] == local(DAY, 10)


def test_fixed_confirmation_is_indivisible_idempotent_and_does_not_double_book(runtime):
    client, reader, factory = runtime
    focus, meetings, _ = configure(client, factory)
    meeting_id, focus_id = task(client, meetings, 60), task(client, focus, 60)
    fixed = [{"task_id": meeting_id, "starts_at": local(DAY, 10),
              "ends_at": local(DAY, 11)}]
    first = preview(client, [meeting_id], fixed=fixed)
    assert first["can_confirm"] and len(first["suggestions"]) == 1
    assert first["suggestions"][0]["placement_reason"] == "FIXED_ELIGIBLE"
    command = uuid4()
    result = confirm(client, [meeting_id], first, command=command, fixed=fixed)
    assert result.status_code == 200, result.text
    before = reader.calls
    repeated = confirm(client, [meeting_id], first, command=command, fixed=fixed)
    assert repeated.status_code == 200 and repeated.json() == result.json()
    assert reader.calls == before  # replay did not reread Google or rebook
    forbidden = preview(client, [focus_id])
    assert not forbidden["suggestions"] and not forbidden["can_confirm"]
    response = confirm(client, [meeting_id], first, command=uuid4(), fixed=fixed)
    assert response.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            ConfirmedTimeBlockRecord)) == 1
        assert session.scalar(select(func.count()).select_from(
            HistoryEventRecord).where(
                HistoryEventRecord.event_type == "TIME_BLOCK_CONFIRMED")) == 1
    effective = client.get("/api/availability/effective", params={
        "from": WEEK.isoformat(), "to": "2027-01-11",
        "timezone_name": ZONE,
    })
    assert effective.status_code == 200, effective.text
    assert not [v for v in effective.json()["issues"] if v["booking_id"]]


def test_priority_revision_alone_invalidates_confirm_without_writing(runtime):
    client, _, factory = runtime
    focus, _, series = configure(client, factory)
    chosen = task(client, focus, 60)
    original = preview(client, [chosen])
    assert original["can_confirm"]
    current = series[0]
    with SqlAlchemyUnitOfWork(factory) as uow:
        next_revision = replace(current.revisions[0], number=2, priority_rank=3)
        uow.eligibility.append_revision(
            OWNER, next_revision, expected_version=1)
        uow.commit()
    result = confirm(client, [chosen], original)
    assert result.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            ConfirmedTimeBlockRecord)) == 0


def test_google_busy_and_fixed_partial_reject_instead_of_fragmenting(runtime):
    client, reader, _ = runtime
    _, meetings, _ = configure(client, runtime[2])
    chosen = task(client, meetings, 60)
    reader.events.append(CalendarCommitment(
        "primary", "busy", "Busy",
        datetime.fromisoformat(local(DAY, 10, 30)),
        datetime.fromisoformat(local(DAY, 10, 45)),
    ))
    fixed = [{"task_id": chosen, "starts_at": local(DAY, 10),
              "ends_at": local(DAY, 11)}]
    offer = preview(client, [chosen], fixed=fixed)
    assert not offer["suggestions"]
    assert not offer["can_confirm"]
    assert offer["unplaced"][0]["reason"] == "FIXED_SLOT_NOT_VERIFIED_FREE_OR_ADMISSIBLE"


def test_capacity_potentials_are_alternatives_not_extra_physical_minutes(runtime):
    client, _, factory = runtime
    focus, meetings, _ = configure(client, factory, include_wednesday=True)
    meeting_id = task(client, meetings, 60)
    response = client.post(f"/api/capacity/weeks/{WEEK}/evaluate", json={
        "task_ids": [meeting_id], "timezone_name": ZONE,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["available_minutes"] == 120  # Tue + Wed, never 240
    alternatives = [item for item in data["by_work_type"]
                    if item["work_type_id"] in (str(focus), str(meetings))]
    assert len(alternatives) == 2
    assert all(item["available_minutes"] == 120
               and item["alternative_potential"] for item in alternatives)
    plan = client.post(f"/api/capacity/weeks/{WEEK}/proposals", json={
        "task_ids": [meeting_id], "timezone_name": ZONE,
    })
    assert plan.status_code == 200, plan.text
    assert plan.json()["baseline"]["available_minutes"] == 120


def test_protected_meeting_precedes_flexible_focus_in_shared_slot(runtime):
    from sqlalchemy import update
    from app.infrastructure.models import TaskRecord

    client, _, factory = runtime
    focus, meetings, _ = configure(client, factory)
    meeting_id, focus_id = task(client, meetings, 60), task(client, focus, 60)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.id == meeting_id)
                        .values(protection="PROTECTED"))
    offer = preview(client, [focus_id, meeting_id])
    assert {item["task_id"] for item in offer["suggestions"]} == {meeting_id}


def test_neutral_wednesday_uses_user_order_when_tuesday_google_busy(runtime):
    client, reader, factory = runtime
    focus, meetings, _ = configure(client, factory, include_wednesday=True)
    meeting_id, focus_id = task(client, meetings, 60), task(client, focus, 60)
    reader.events.append(CalendarCommitment(
        "primary", "tuesday", "Busy",
        datetime.fromisoformat(local(DAY, 10)),
        datetime.fromisoformat(local(DAY, 11)),
    ))
    offer = preview(client, [meeting_id, focus_id])
    assert {item["task_id"] for item in offer["suggestions"]} == {meeting_id}
    assert offer["suggestions"][0]["priority_rank"] is None
    assert offer["suggestions"][0]["starts_at"] == local(date(2027, 1, 6), 10)
