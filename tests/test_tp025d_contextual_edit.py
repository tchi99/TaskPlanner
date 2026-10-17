"""TP-025D: no silent mutation, shared physical capacity and stale-preview safety."""
from datetime import date, datetime
from uuid import uuid4, UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.schedule_scopes import compatibility_scope_id
from app.domain.time_blocks import ConfirmedTimeBlock
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

OWNER = "urn:taskplanner:local"
ZONE = "America/Toronto"
DAY = date(2027, 1, 5)
BASE = "/api/availability/eligibility-edits"


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
            with SqlAlchemyUnitOfWork(factory) as uow:
                uow.schedule_scopes.ensure_compatibility(OWNER)
                uow.commit()
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def setup(client):
    general = client.post("/api/availability/rules", json={
        "effective_from": "2027-01-04", "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": "10:00",
        "ends_at_local": "12:00", "kind": "GENERAL",
    })
    assert general.status_code == 201, general.text
    types = []
    for name in ("Focus", "Reunions"):
        result = client.post("/api/work-types", json={"name": name})
        assert result.status_code == 201, result.text
        types.append(result.json()["id"])
    return types


def draft(work_type_id, **changes):
    value = dict(
        draft_id=str(uuid4()), series_id=None, legacy_rule_id=None,
        scope_id=str(compatibility_scope_id(OWNER)), work_type_id=work_type_id,
        expected_version=0, expected_legacy_version=None,
        effective_from=DAY.isoformat(), timezone_name=ZONE, days_of_week=[1],
        starts_at_local="10:00", ends_at_local="12:00",
        priority_rank=None, enabled=True, start_fold=None, end_fold=None,
    )
    value.update(changes)
    return value


def preview(client, value):
    result = client.post(BASE + "/preview", json=value)
    assert result.status_code == 200, result.text
    return result.json()


def confirm(client, value, projected, command_id=None, **options):
    return client.post(BASE + "/confirm", json={
        **value, "fingerprint": projected["fingerprint"],
        "command_id": command_id or str(uuid4()), "confirmed": True,
        "acknowledge_bookings": False, **options,
    })


def test_shared_creation_and_replay_one_physical_interval(runtime):
    client, _ = runtime
    focus, meeting = setup(client)
    for typ, rank in ((focus, 1), (meeting, None)):
        value = draft(typ, priority_rank=rank)
        projection = preview(client, value)
        assert projection["blocking_issues"] == []
        assert projection["after_physical_minutes"] == projection["before_physical_minutes"]
        assert projection["after_physical_minutes"] > 0
        command_id = str(uuid4())
        result = confirm(client, value, projection, command_id)
        assert result.status_code == 200, result.text
        assert confirm(client, value, projection, command_id).json() == result.json()
    rendered = client.get("/api/availability/eligibility-week", params={
        "week_start": "2027-01-04", "timezone_name": ZONE})
    assert rendered.status_code == 200, rendered.text
    week = rendered.json()
    assert week["physical_minutes"] == 120
    assert sorted(v["minutes"] for v in week["potential_minutes"]) == [120, 120]
    assert any(len(fragment["choices"]) == 2 for fragment in week["fragments"])


def test_stale_priority_only_edit_and_owned_revision(runtime):
    client, _ = runtime
    focus, _ = setup(client)
    initial = draft(focus)
    receipt = confirm(client, initial, preview(client, initial)).json()
    series = receipt["series_id"]
    old = draft(focus, series_id=series, expected_version=1, priority_rank=1)
    old_preview = preview(client, old)
    competing = draft(focus, series_id=series, expected_version=1, priority_rank=2)
    assert confirm(client, competing, preview(client, competing)).status_code == 200
    stale = confirm(client, old, old_preview)
    assert stale.status_code == 409, stale.text
    current = client.get(BASE + "/series/" + series).json()
    assert current["version"] == 2
    assert [r["priority_rank"] for r in current["revisions"]] == [None, 2]
    assert client.get(BASE + "/series/" + str(uuid4())).status_code == 404


def test_opt_in_from_preferred_preserves_legacy_and_rejects_protected(runtime):
    client, _ = runtime
    focus, meeting = setup(client)
    legacy = client.post("/api/availability/rules", json={
        "effective_from": "2027-01-04", "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": "10:00",
        "ends_at_local": "12:00", "kind": "CATEGORIZED",
        "work_type_id": focus, "mode": "PREFERRED",
    }).json()
    proposed = draft(focus, legacy_rule_id=legacy["id"],
                     expected_legacy_version=legacy["version"])
    outcome = preview(client, proposed)
    assert not outcome["blocking_issues"], outcome
    assert confirm(client, proposed, outcome).status_code == 200
    after = client.get("/api/availability/rules/" + legacy["id"]).json()
    assert after["version"] == 2 and after["revisions"][0]["mode"] == "PREFERRED"
    assert after["revisions"][-1]["supersedes_future"] is True
    future = draft(meeting)
    assert confirm(client, future, preview(client, future)).status_code == 200
    book = client.get("/api/availability/eligibility-week", params={
        "week_start": "2027-01-04", "timezone_name": ZONE}).json()
    assert any(len(fragment["choices"]) == 2 for fragment in book["fragments"])
    protected = client.post("/api/availability/rules", json={
        "effective_from": "2027-01-04", "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": "10:00",
        "ends_at_local": "12:00", "kind": "CATEGORIZED",
        "work_type_id": meeting, "mode": "PROTECTED",
    })
    assert protected.status_code == 201, protected.text
    rejected = client.post(BASE + "/preview", json=draft(
        meeting, legacy_rule_id=protected.json()["id"],
        expected_legacy_version=1))
    assert rejected.status_code == 422


def test_booking_ack_and_future_booking_persistence(runtime):
    client, factory = runtime
    focus, _ = setup(client)
    task = client.post("/api/tasks", json={"title": "Protected reservation", "estimated_minutes": 60})
    assert task.status_code == 201, task.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        booking = ConfirmedTimeBlock(
            week_start=date(2027, 1, 4), task_id=UUID(task.json()["id"]), segment_id=None,
            work_type_id=UUID(focus),
            starts_at=datetime(2027, 1, 5, 10, tzinfo=ZoneInfo(ZONE)),
            ends_at=datetime(2027, 1, 5, 11, tzinfo=ZoneInfo(ZONE)),
            scope_id=compatibility_scope_id(OWNER),
        )
        uow.time_blocks.add(booking)
        uow.commit()
    value = draft(focus)
    proposed = preview(client, value)
    assert proposed["booking_inventory"]
    assert confirm(client, value, proposed).status_code == 422
    accepted = confirm(client, value, proposed, acknowledge_bookings=True)
    assert accepted.status_code == 200, accepted.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        saved = uow.time_blocks.get(booking.id)
        assert saved.status == "CONFIRMED" and saved.starts_at == booking.starts_at


def test_past_edit_and_nonexistent_dst_are_rejected(runtime):
    client, _ = runtime
    focus, _ = setup(client)
    assert client.post(BASE + "/preview", json=draft(
        focus, effective_from="2026-01-01")).status_code == 422
    # In Toronto, 02:30 on the March spring-forward day does not exist.
    rule = draft(focus, effective_from="2027-03-13", days_of_week=[6],
                 starts_at_local="02:30", ends_at_local="03:30")
    outcome = preview(client, rule)
    assert any("NONEXISTENT_LOCAL_TIME" in v for v in outcome["blocking_issues"])
