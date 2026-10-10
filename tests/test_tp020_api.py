from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


WEEK = "/api/capacity/weeks/2026-10-05"


def create_block(client, start="08:00", end="09:00", work_type_id=None):
    return client.post(WEEK + "/blocks", json={
        "starts_at": f"2026-10-05T{start}:00-04:00",
        "ends_at": f"2026-10-05T{end}:00-04:00",
        "work_type_id": work_type_id,
    })


def test_blocks_persist_weekly_and_delete_with_week_isolation(client):
    work_type_id = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    response = create_block(client, work_type_id=work_type_id)
    assert response.status_code == 201
    block_id = response.json()["id"]
    assert response.json()["minutes"] == 60
    week = client.get(WEEK).json()
    assert week["capacity"]["available_minutes"] == 60
    assert week["capacity"]["by_work_type"][0]["work_type_id"] == work_type_id
    assert week["blocks"][0]["id"] == block_id
    assert client.get("/api/capacity/weeks/2026-10-12").json()["blocks"] == []
    assert client.delete(
        f"/api/capacity/weeks/2026-10-12/blocks/{block_id}"
    ).status_code == 404
    assert client.delete(WEEK + f"/blocks/{block_id}").status_code == 204
    assert client.get(WEEK).json()["blocks"] == []


def test_validation_overlap_and_unknown_work_type_are_rejected(client):
    assert create_block(client).status_code == 201
    assert create_block(client, "08:30", "09:30").status_code == 422
    assert create_block(client, "09:00", "10:00").status_code == 201
    assert create_block(client, "10:00", "11:00", str(uuid4())).status_code == 422
    assert client.get("/api/capacity/weeks/2026-10-06").status_code == 422
    assert client.post(WEEK + "/blocks", json={
        "starts_at": "2026-10-05T11:00:00",
        "ends_at": "2026-10-05T12:00:00",
    }).status_code == 422
    assert len(client.get(WEEK).json()["blocks"]) == 2


def test_plan_preview_reports_known_overload_and_unknown_segments(client):
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    assert create_block(client, work_type_id=focus).status_code == 201
    parent = client.post("/api/tasks", json={
        "title": "Parent", "estimated_minutes": 700
    }).json()["id"]
    assert client.post(f"/api/tasks/{parent}/clarify", json={
        "work_type_id": focus
    }).status_code == 200
    assert client.post(f"/api/tasks/{parent}/segments", json={
        "title": "Small", "estimated_minutes": 61
    }).status_code == 201
    assert client.post(f"/api/tasks/{parent}/segments", json={
        "title": "Unknown"
    }).status_code == 201
    result = client.post(WEEK + "/evaluate", json={"task_ids": [parent]})
    assert result.status_code == 200
    data = result.json()
    assert data["known_demand_minutes"] == 61
    assert data["unestimated_units"] == 1
    assert data["status"] == "OVER_CAPACITY"
    assert data["by_work_type"][0]["remaining_minutes"] == -1
    assert client.post(WEEK + "/evaluate", json={
        "task_ids": [parent, parent]
    }).status_code == 422
    assert client.post(WEEK + "/evaluate", json={
        "task_ids": [str(uuid4())]
    }).status_code == 404


def test_inbox_not_committed_or_modified_by_evaluation(client):
    task_id = client.post("/api/tasks", json={
        "title": "Inbox", "estimated_minutes": 40
    }).json()["id"]
    assert client.post(WEEK + "/evaluate", json={
        "task_ids": [task_id]
    }).status_code == 422
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "INBOX"
    assert client.post(WEEK + "/evaluate", json={"task_ids": []}).json()["status"] == "FEASIBLE"
