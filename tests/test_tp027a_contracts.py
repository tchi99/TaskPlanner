"""TP-027A: backend graphical edit contracts, concurrency and recurrence safety."""
from datetime import date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

ZONE = "America/Toronto"
EDIT = "/api/availability/eligibility-edits"
ENVELOPE = "/api/availability/weekly-schedule"
WEEK = "/api/availability/eligibility-week"


class Calendar:
    def list_commitments(self, start, end, timezone_name):
        return ()


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_calendar_reader] = lambda: Calendar()
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _preview(client, path, payload):
    response = client.post(path + "/preview", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, path, payload, preview, **fields):
    return client.post(path + "/confirm", json={
        **payload, "fingerprint": preview["fingerprint"],
        "confirmed": True, "command_id": str(uuid4()), **fields,
    })


def _setup(client):
    parent = client.post("/api/schedule-scopes", json={"name": "Travail"})
    assert parent.status_code == 201, parent.text
    scope = parent.json()["id"]
    work_type = client.post("/api/work-types", json={"name": "Focus", "scope_id": scope})
    assert work_type.status_code == 201, work_type.text
    typ = work_type.json()["id"]
    grid = {
        "effective_from": "2027-01-04", "timezone_name": ZONE,
        "expected_versions": {},
        "sections": [{
            "weekday": day, "kind": "GENERAL", "scope_id": scope,
            "work_type_id": None,
            "slots": [{"starts_at_local": "10:00", "ends_at_local": "12:00"}],
        } for day in (1, 3)],
    }
    applied = _confirm(client, ENVELOPE, grid, _preview(client, ENVELOPE, grid))
    assert applied.status_code == 200, applied.text
    value = {
        "draft_id": str(uuid4()), "series_id": None, "scope_id": scope,
        "work_type_id": typ, "expected_version": 0,
        "effective_from": "2027-01-05", "timezone_name": ZONE,
        "days_of_week": [1, 3], "starts_at_local": "10:00",
        "ends_at_local": "12:00", "enabled": True, "priority_rank": 1,
    }
    original = _confirm(client, EDIT, value, _preview(client, EDIT, value))
    assert original.status_code == 200, original.text
    return scope, typ, original.json()["series_id"]


def _target(scope, typ, series_id, *, expected_version=1, **changes):
    draft = {
        "draft_id": str(uuid4()), "series_id": series_id, "scope_id": scope,
        "work_type_id": typ, "expected_version": expected_version,
        "effective_from": "2027-01-11", "timezone_name": ZONE,
        "days_of_week": [1], "target_days_of_week": [1],
        "starts_at_local": "10:30", "ends_at_local": "11:30",
        "priority_rank": 1, "enabled": True, "exception_decisions": [],
    }
    draft.update(changes)
    return draft


def _dated(series_id, day, action, *, exception_id=None, expected_version=0,
           starts_at=None, ends_at=None, enabled=True):
    return {
        "draft_id": str(uuid4()), "series_id": series_id,
        "exception_id": exception_id, "expected_version": expected_version,
        "original_local_date": day, "timezone_name": ZONE, "action": action,
        "starts_at": starts_at, "ends_at": ends_at, "enabled": enabled,
    }


def test_targeted_tuesday_edit_preserves_thursday_and_replay(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    payload = _target(scope, typ, source)
    expected = _preview(client, EDIT, payload)
    assert expected["blocking_issues"] == []
    assert "3" in expected["preserved_weekday_series"]
    command_id = str(uuid4())
    first = _confirm(client, EDIT, payload, expected, command_id=command_id)
    assert first.status_code == 200, first.text
    replay = _confirm(client, EDIT, payload, expected, command_id=command_id)
    assert replay.json() == first.json()
    assert client.get(EDIT + "/series/" + source).json()["version"] == 2
    new_series = first.json()["series_id"]
    assert new_series != source
    shown = client.get(WEEK, params={"week_start": "2027-01-11", "timezone_name": ZONE,
                                    "scope_id": scope})
    assert shown.status_code == 200, shown.text
    objects = shown.json()["editable_permissions"]
    assert {obj["original_local_date"] for obj in objects} == {"2027-01-12", "2027-01-14"}
    assert {obj["series_id"] for obj in objects} == {
        new_series, expected["preserved_weekday_series"]["3"],
    }
    durations = {obj["original_local_date"]: (datetime.fromisoformat(obj["ends_at"]) -
                 datetime.fromisoformat(obj["starts_at"])).total_seconds() / 60
                 for obj in objects}
    assert durations == {"2027-01-12": 60, "2027-01-14": 120}
    assert shown.json()["physical_minutes"] == 240


def test_two_cutovers_same_effective_date_and_stale_preview(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    first = _target(scope, typ, source)
    next_id = _confirm(client, EDIT, first, _preview(client, EDIT, first)).json()["series_id"]
    second = _target(scope, typ, next_id, starts_at_local="10:45", ends_at_local="11:45")
    stale = _preview(client, EDIT, second)
    competitor = _target(scope, typ, next_id, starts_at_local="10:15", ends_at_local="11:15")
    success = _confirm(client, EDIT, competitor, _preview(client, EDIT, competitor))
    assert success.status_code == 200, success.text
    rejected = _confirm(client, EDIT, second, stale)
    assert rejected.status_code == 409, rejected.text
    assert client.get(EDIT + "/series/" + next_id).json()["version"] == 2


def test_dated_remove_and_move_are_scoped_and_versioned(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    day = "2027-01-14"
    changed = _dated(source, day, "MOVE",
                     starts_at="2027-01-14T10:15:00-05:00",
                     ends_at="2027-01-14T11:45:00-05:00")
    planned = _preview(client, EDIT + "/exceptions", changed)
    command_id = str(uuid4())
    committed = _confirm(client, EDIT + "/exceptions", changed, planned,
                         command_id=command_id)
    assert committed.status_code == 200, committed.text
    exc_id = committed.json()["exception_id"]
    assert _confirm(client, EDIT + "/exceptions", changed, planned,
                    command_id=command_id).json() == committed.json()
    disabled = _dated(source, day, "REMOVE", exception_id=exc_id,
                      expected_version=1, starts_at=None, ends_at=None)
    before = _preview(client, EDIT + "/exceptions", disabled)
    assert before["after"]["action"] == "REMOVE"
    assert _confirm(client, EDIT + "/exceptions", disabled, before).status_code == 200
    week = client.get(WEEK, params={"week_start": "2027-01-11", "timezone_name": ZONE,
                                    "scope_id": scope}).json()
    assert {obj["original_local_date"] for obj in week["editable_permissions"]} == {"2027-01-12"}
    stale = _confirm(client, EDIT + "/exceptions", disabled, before)
    assert stale.status_code == 409, stale.text


def test_targeted_cutover_demands_explicit_affected_exception_decision(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    old = _dated(source, "2027-01-12", "REMOVE")
    assert _confirm(client, EDIT + "/exceptions", old,
                    _preview(client, EDIT + "/exceptions", old)).status_code == 200
    payload = _target(scope, typ, source)
    proposed = _preview(client, EDIT, payload)
    assert proposed["unresolved_exceptions"]
    assert "UNRESOLVED_ELIGIBILITY_EXCEPTIONS" in proposed["blocking_issues"]
    assert _confirm(client, EDIT, payload, proposed).status_code == 422
    exception_id = proposed["unresolved_exceptions"][0]["exception_id"]
    payload["exception_decisions"] = [{
        "exception_id": exception_id, "expected_version": 1, "action": "DISABLE",
    }]
    resolved = _preview(client, EDIT, payload)
    assert resolved["unresolved_exceptions"] == []
    done = _confirm(client, EDIT, payload, resolved)
    assert done.status_code == 200, done.text


def test_parent_envelope_cannot_newly_strand_permission(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    grid = {
        "effective_from": "2027-01-11", "timezone_name": ZONE,
        "expected_versions": {},
        "sections": [{"weekday": 1, "kind": "GENERAL", "scope_id": scope,
                      "work_type_id": None,
                      "slots": [{"starts_at_local": "10:30", "ends_at_local": "11:30"}]}],
    }
    planned = _preview(client, ENVELOPE, grid)
    assert "ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE" in planned["invalid_conflicts"]
    assert _confirm(client, ENVELOPE, grid, planned).status_code == 422
    week = client.get(WEEK, params={"week_start": "2027-01-11", "timezone_name": ZONE,
                                    "scope_id": scope}).json()
    assert week["physical_minutes"] == 240


def test_dst_nonexistent_dated_move_is_rejected(runtime):
    client, _ = runtime
    scope, typ, source = _setup(client)
    invalid = _dated(source, "2027-01-12", "MOVE",
                     starts_at="2027-03-14T02:30:00-05:00",
                     ends_at="2027-03-14T03:30:00-04:00")
    # The source occurrence remains January's; a remote MOVE outside 93 days
    # or an invalid civil destination must never be committed.
    result = client.post(EDIT + "/exceptions/preview", json=invalid)
    assert result.status_code in (409, 422), result.text


def test_confirmed_booking_outside_parent_envelope_remains_visible(runtime):
    from app.domain.time_blocks import ConfirmedTimeBlock
    client, factory = runtime
    scope, typ, source = _setup(client)
    task = client.post("/api/tasks", json={
        "title": "Booking outside physical envelope", "estimated_minutes": 60,
    })
    assert task.status_code == 201, task.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        booking = ConfirmedTimeBlock(
            week_start=date(2027, 1, 11), task_id=UUID(task.json()["id"]),
            segment_id=None, work_type_id=UUID(typ),
            starts_at=datetime(2027, 1, 12, 13, tzinfo=ZoneInfo(ZONE)),
            ends_at=datetime(2027, 1, 12, 14, tzinfo=ZoneInfo(ZONE)),
            scope_id=UUID(scope),
        )
        uow.time_blocks.add(booking)
        uow.commit()
    result = client.get(WEEK, params={
        "week_start": "2027-01-11", "timezone_name": ZONE, "scope_id": scope,
    })
    assert result.status_code == 200, result.text
    assert any(item["booking_id"] == str(booking.id)
               and item["outside_envelope"] for item in result.json()["occupations"])


def test_targeted_cutover_replaces_exception_atomically(runtime):
    client, factory = runtime
    scope, typ, source = _setup(client)
    original_exception = _dated(source, "2027-01-12", "REMOVE")
    created = _confirm(client, EDIT + "/exceptions", original_exception,
                       _preview(client, EDIT + "/exceptions", original_exception))
    assert created.status_code == 200, created.text
    original_id = created.json()["exception_id"]
    draft = _target(scope, typ, source, exception_decisions=[{
        "exception_id": original_id, "expected_version": 1,
        "action": "REPLACE", "replacement_action": "MOVE",
        "starts_at": "2027-01-12T10:45:00-05:00",
        "ends_at": "2027-01-12T11:45:00-05:00",
    }])
    proposed = _preview(client, EDIT, draft)
    assert proposed["unresolved_exceptions"] == []
    assert proposed["exception_decisions"][0]["action"] == "REPLACE"
    response = _confirm(client, EDIT, draft, proposed)
    assert response.status_code == 200, response.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        previous = uow.eligibility.get_exception(UUID(original_id),
                                                 "urn:taskplanner:local")
        assert previous.version == 2 and not previous.enabled
        successor = uow.eligibility.get_exception(
            UUID(proposed["exception_decisions"][0]["successor_id"]),
            "urn:taskplanner:local",
        )
        assert successor.enabled and successor.action.value == "MOVE"
        assert successor.series_id == UUID(response.json()["series_id"])
