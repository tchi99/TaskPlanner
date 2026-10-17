"""TP-025C: visual reads never duplicate minutes or invent Google verification."""
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.calendar import CalendarCommitment
from app.domain.eligibility import EligibilityRevision, EligibilitySeries
from app.domain.schedule_scopes import compatibility_scope_id
from app.domain.time_blocks import ConfirmedTimeBlock
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.google_calendar import GoogleCalendarNotConfigured
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader

OWNER = "urn:taskplanner:local"
ZONE = "America/Toronto"
WEEK = date(2027, 1, 4)


class Reader:
    def __init__(self):
        self.events = []
        self.not_configured = False

    def list_commitments(self, start, end, timezone_name):
        assert timezone_name == ZONE
        if self.not_configured:
            raise GoogleCalendarNotConfigured("No credential")
        return tuple(self.events)


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


def civil(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute,
                    tzinfo=ZoneInfo(ZONE))


def general(client, week=WEEK, *, weekdays=(1,), start="10:00", end="11:00"):
    response = client.post("/api/availability/rules", json={
        "effective_from": week.isoformat(), "timezone_name": ZONE,
        "days_of_week": list(weekdays), "starts_at_local": start,
        "ends_at_local": end, "kind": "GENERAL",
    })
    assert response.status_code == 201, response.text


def add_shared(client, factory, count=3):
    general(client)
    scope = compatibility_scope_id(OWNER)
    types = []
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.schedule_scopes.ensure_compatibility(OWNER)
        uow.commit()
    for index in range(count):
        response = client.post("/api/work-types", json={"name": "Type " + str(index)})
        assert response.status_code == 201, response.text
        work_type = response.json()["id"]
        types.append(work_type)
        with SqlAlchemyUnitOfWork(factory) as uow:
            series_id = uuid4()
            rev = EligibilityRevision(
                series_id, 1, WEEK, None, ZONE, (1,), "10:00", "11:00",
                priority_rank=index + 1)
            uow.eligibility.add(EligibilitySeries(
                series_id, OWNER, scope, __import__("uuid").UUID(work_type), 1, (rev,)))
            uow.commit()
    return types


def get_week(client, week=WEEK, **params):
    return client.get("/api/availability/eligibility-week",
                      params={"week_start": week.isoformat(),
                              "timezone_name": ZONE, **params})


def test_three_admissibilities_share_one_physical_hour_with_source_revision(runtime):
    client, _, factory = runtime
    ids = add_shared(client, factory)
    response = get_week(client)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["projection"] == "PHYSICAL_ELIGIBILITY_NON_ADDITIVE"
    assert value["physical_minutes"] == 60
    assert value["verified_free_minutes"] == 60
    assert value["calendar_checked"] is True
    assert len(value["potential_minutes"]) == 3
    assert {v["work_type_id"] for v in value["potential_minutes"]} == set(ids)
    assert all(v["minutes"] == 60 and v["non_additive"]
               for v in value["potential_minutes"])
    concurrent = [fragment for fragment in value["fragments"] if len(fragment["choices"]) == 3]
    assert len(concurrent) == 1
    assert concurrent[0]["minutes"] == 60
    assert [c["priority_rank"] for c in sorted(
        concurrent[0]["choices"], key=lambda c: c["priority_rank"])] == [1, 2, 3]
    assert all(choice["source_details"][0]["revision"] == 1
               and choice["source_details"][0]["effective_from"] == WEEK.isoformat()
               for choice in concurrent[0]["choices"])
    assert value["proposal_state"] == "NOT_REQUESTED"


def test_local_booking_and_google_busy_union_without_false_free(runtime):
    client, reader, factory = runtime
    ids = add_shared(client, factory, count=2)
    day = date(2027, 1, 5)
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.time_blocks.add(ConfirmedTimeBlock(
            week_start=WEEK, task_id=uuid4(), segment_id=None,
            work_type_id=__import__("uuid").UUID(ids[0]),
            starts_at=civil(day, 10), ends_at=civil(day, 10, 30),
            scope_id=compatibility_scope_id(OWNER)))
        uow.commit()
    reader.events.append(CalendarCommitment(
        "primary", "busy", "Busy meeting",
        civil(day, 10, 15), civil(day, 11)))
    response = get_week(client)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["physical_minutes"] == 60
    assert value["local_occupied_minutes"] == 30
    assert value["verified_occupied_minutes"] == 60
    assert value["verified_free_minutes"] == 0
    assert {v["kind"] for v in value["occupations"]} == {
        "LOCAL_CONFIRMED", "GOOGLE_VERIFIED"}
    assert any(issue["code"] == "BOOKING_CONFLICTS_WITH_GOOGLE"
               for issue in value["issues"])
    reader.not_configured = True
    unavailable = get_week(client)
    assert unavailable.status_code == 200, unavailable.text
    payload = unavailable.json()
    assert payload["calendar_state"] == "NOT_CONFIGURED"
    assert payload["calendar_checked"] is False
    assert payload["verified_free_minutes"] is None
    assert payload["verified_occupied_minutes"] is None
    assert payload["local_occupied_minutes"] == 30
    assert {v["kind"] for v in payload["occupations"]} == {"LOCAL_CONFIRMED"}


def test_scope_is_owner_scoped_and_dst_sunday_has_23_hours(runtime):
    client, _, _ = runtime
    assert get_week(client, scope_id=str(uuid4())).status_code == 404
    spring = date(2027, 3, 8)
    general(client, spring, weekdays=(6,), start="01:00", end="04:00")
    response = get_week(client, spring)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["days"][6]["minutes"] == 1380
    assert payload["physical_minutes"] == 120
    sunday = [f for f in payload["fragments"] if f["weekday"] == 6]
    assert len(sunday) == 1
    assert sunday[0]["minutes"] == 120
    assert sunday[0]["starts_at_local"].endswith("-05:00")
    assert sunday[0]["ends_at_local"].endswith("-04:00")
    assert sunday[0]["end_minute"] - sunday[0]["start_minute"] == 120
