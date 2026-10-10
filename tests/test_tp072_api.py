"""Read-only TP-072 endpoint and compatibility with daily/weekly review APIs."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, TaskRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_projections_are_read_only_and_existing_reviews_remain_available(setup):
    client, factory = setup
    response = client.post("/api/tasks", json={
        "title": "A long project action", "estimated_minutes": 120,
    })
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    assert client.post("/api/tasks/" + task_id + "/clarify", json={}).status_code == 200
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(HistoryEventRecord))
        task_before = session.get(TaskRecord, task_id).status

    answer = client.get("/api/behavior")
    assert answer.status_code == 200, answer.text
    value = answer.json()
    assert value["trends"] == []
    assert value["minimum_samples"] == 3
    assert value["changes_applied"] is False
    assert any(i["code"] == "SPLIT_LARGE_UNIT" and i["task_id"] == task_id
               and i["requires_confirmation"] for i in value["interventions"])
    assert all("payload" not in i and "notes" not in i for i in value["interventions"])
    assert client.get("/api/review/daily", params={
        "day": "2026-10-10", "timezone_name": "America/Toronto",
    }).status_code == 200
    assert client.get("/api/review/weekly", params={
        "week_start": "2026-10-05", "timezone_name": "America/Toronto",
    }).status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HistoryEventRecord)) == before
        assert session.get(TaskRecord, task_id).status == task_before


def test_old_observed_event_reappears_without_silently_modifying_task(setup):
    client, factory = setup
    created = client.post("/api/tasks", json={"title": "Quiet task"})
    task_id = created.json()["id"]
    assert client.post("/api/tasks/" + task_id + "/clarify", json={}).status_code == 200
    old = datetime.now(timezone.utc) - timedelta(days=20)
    with factory() as session:
        for item in session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.task_id == task_id
        )):
            item.recorded_at = old
        session.commit()
    response = client.get("/api/behavior")
    assert response.status_code == 200, response.text
    row = next(i for i in response.json()["interventions"] if i["task_id"] == task_id)
    assert row["code"] == "REVISIT_QUIET"
    assert row["requires_confirmation"] is True
    assert client.get("/api/tasks/" + task_id + "/detail").json()["status"] == "TODO"
