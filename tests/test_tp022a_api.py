"""TP-022A rule API uses real SQLAlchemy transactions, not fake repositories."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.recurring_availability import create_rule
from app.domain.recurring_availability import RuleKind
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import (
    AvailabilityBlockRecord, HistoryEventRecord,
    RecurringAvailabilityRevisionRecord,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def next_monday():
    today = date.today()
    return today + timedelta(days=7 + (7 - today.weekday()) % 7)


def payload(start):
    return {
        "effective_from": start.isoformat(),
        "timezone_name": "America/Toronto", "days_of_week": [1, 3],
        "starts_at_local": "09:00", "ends_at_local": "11:30",
        "kind": "GENERAL",
    }


def test_create_expand_revise_and_disable_with_audit(database):
    client, factory = database
    monday = next_monday()
    created = client.post("/api/availability/rules", json=payload(monday))
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["version"] == 1
    assert data["revisions"][0]["kind"] == "GENERAL"
    assert data["revisions"][0]["mode"] is None
    rule_id = data["id"]
    assert len(client.get("/api/availability/rules").json()) == 1
    assert client.get(f"/api/availability/rules/{rule_id}").status_code == 200

    response = client.get("/api/availability/rules/occurrences", params={
        "from": monday.isoformat(), "to": (monday + timedelta(days=7)).isoformat(),
    })
    assert response.status_code == 200, response.text
    values = response.json()
    assert values["projection"] == "RAW_DECLARATIONS_NOT_FREE_CAPACITY"
    assert len(values["occurrences"]) == 2
    assert not values["issues"]
    duration = sum((
        __import__("datetime").datetime.fromisoformat(v["ends_at"]) -
        __import__("datetime").datetime.fromisoformat(v["starts_at"])
    ).total_seconds() for v in values["occurrences"])
    assert duration == 5 * 3600

    next_week = monday + timedelta(days=7)
    change = {**payload(next_week), "starts_at_local": "10:00", "expected_version": 1}
    revised = client.patch(f"/api/availability/rules/{rule_id}", json=change)
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2
    assert [v["number"] for v in revised.json()["revisions"]] == [1, 2]
    assert client.patch(f"/api/availability/rules/{rule_id}", json=change).status_code == 409

    old = client.get("/api/availability/rules/occurrences", params={
        "from": monday.isoformat(), "to": next_week.isoformat(),
    }).json()
    assert {v["revision"] for v in old["occurrences"]} == {1}
    disabled_day = monday + timedelta(days=14)
    assert client.delete(f"/api/availability/rules/{rule_id}", params={
        "expected_version": 2, "effective_from": disabled_day.isoformat(),
    }).status_code == 204
    after = client.get("/api/availability/rules/occurrences", params={
        "from": disabled_day.isoformat(),
        "to": (disabled_day + timedelta(days=7)).isoformat(),
    }).json()
    assert after["occurrences"] == []
    with factory() as session:
        revisions = session.scalars(select(RecurringAvailabilityRevisionRecord)).all()
        history = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_type == "AVAILABILITY_RULE"
        ).order_by(HistoryEventRecord.sequence)).all()
        assert len(revisions) == 3
        assert [v.event_type for v in history] == [
            "AVAILABILITY_RULE_CREATED", "AVAILABILITY_RULE_CHANGED",
            "AVAILABILITY_RULE_DISABLED",
        ]
        assert all(v.task_id is None for v in history)


def test_categorized_default_mode_validation_and_existing_manual_blocks(database):
    client, factory = database
    monday = next_monday()
    work_type = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    weekly = f"/api/capacity/weeks/{monday.isoformat()}"
    assert client.post(weekly + "/blocks", json={
        "starts_at": f"{monday.isoformat()}T08:00:00+00:00",
        "ends_at": f"{monday.isoformat()}T09:00:00+00:00",
    }).status_code == 201
    candidate = {
        **payload(monday), "kind": "CATEGORIZED", "work_type_id": work_type,
    }
    created = client.post("/api/availability/rules", json=candidate)
    assert created.status_code == 201, created.text
    assert created.json()["revisions"][0]["mode"] == "PREFERRED"
    assert client.post("/api/availability/rules", json={
        **candidate, "mode": "PROTECTED",
    }).status_code == 201
    assert client.post("/api/availability/rules", json={
        **candidate, "work_type_id": str(uuid4()),
    }).status_code == 422
    assert client.post("/api/availability/rules", json={
        **candidate, "days_of_week": [1, 1],
    }).status_code == 422
    assert client.get(weekly).json()["capacity"]["available_minutes"] == 60
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AvailabilityBlockRecord)) == 1
        assert session.scalar(select(func.count()).select_from(RecurringAvailabilityRevisionRecord)) == 2


def test_boundaries_and_owner_isolation(database):
    client, factory = database
    monday = next_monday()
    assert client.get("/api/availability/rules/occurrences", params={
        "from": monday.isoformat(),
        "to": (monday + timedelta(days=94)).isoformat(),
    }).status_code == 422
    other_id = uuid4()
    with factory() as session:
        pass
    other = create_rule(
        SqlAlchemyUnitOfWork(factory), "another-owner",
        dict(effective_from=monday, valid_until=None,
             timezone_name="America/Toronto", days_of_week=(1, 3),
             starts_at_local="09:00", ends_at_local="11:30",
             kind=RuleKind.GENERAL, work_type_id=None, mode=None,
             enabled=True, start_fold=None, end_fold=None),
    )
    assert client.get("/api/availability/rules").json() == []
    assert client.get(f"/api/availability/rules/{other.id}").status_code == 404
