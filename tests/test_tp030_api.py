from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import TaskRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app

WEEK = "/api/capacity/weeks/2026-10-05"


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_weekly_options_api_is_side_effect_free_and_exposes_consequences(runtime):
    client, engine = runtime
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    assert client.post(WEEK + "/blocks", json={
        "starts_at": "2026-10-05T08:00:00-04:00",
        "ends_at": "2026-10-05T09:00:00-04:00",
        "work_type_id": focus,
    }).status_code == 201
    ids = []
    for title, protection, estimate in (("Must", "PROTECTED", 40), ("May", "FLEXIBLE", 30)):
        task_id = client.post("/api/tasks", json={
            "title": title, "estimated_minutes": estimate,
        }).json()["id"]
        assert client.post(f"/api/tasks/{task_id}/clarify", json={
            "work_type_id": focus,
        }).status_code == 200
        assert client.patch(f"/api/tasks/{task_id}/protection", json={
            "protection": protection,
        }).status_code == 200
        ids.append(task_id)

    result = client.post(WEEK + "/proposals", json={"task_ids": ids})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["state"] == "PROPOSED"
    assert data["baseline"]["status"] == "OVER_CAPACITY"
    assert data["baseline"]["known_demand_minutes"] == 70
    assert set(data["candidate_task_ids"]) == set(ids)
    kinds = [option["kind"] for option in data["options"]]
    assert kinds == ["KEEP", "DEFER", "REVIEW_SCOPE", "CONSIDER_DELEGATION"]
    deferred = data["options"][1]
    assert deferred["excluded_task_ids"] == [ids[1]]
    assert deferred["capacity"]["status"] == "FEASIBLE"
    assert deferred["requires_confirmation"] is True
    assert data["options"][2]["capacity"] is None
    assert len({option["id"] for option in data["options"]}) == len(kinds)
    assert client.get(f"/api/tasks/{ids[1]}").json()["status"] == "TODO"
    assert len(client.get(WEEK).json()["blocks"]) == 1
    with Session(engine) as session:
        assert len(session.scalars(select(TaskRecord)).all()) == 2


def test_proposal_validation_and_missing_task(runtime):
    client, _ = runtime
    id_ = str(uuid4())
    assert client.post(WEEK + "/proposals", json={"task_ids": [id_]}).status_code == 404
    assert client.post(WEEK + "/proposals", json={"task_ids": [id_, id_]}).status_code == 422
    assert client.post("/api/capacity/weeks/2026-10-06/proposals", json={"task_ids": []}).status_code == 422
    task_id = client.post("/api/tasks", json={"title": "Inbox"}).json()["id"]
    assert client.post(WEEK + "/proposals", json={"task_ids": [task_id]}).status_code == 422
    assert client.post(WEEK + "/proposals", json={"task_ids": []}).json()["options"][0]["kind"] == "KEEP"
