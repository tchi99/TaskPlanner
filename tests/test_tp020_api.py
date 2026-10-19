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


def test_inbox_not_committed_or_modified_by_evaluation(client):
    task_id = client.post("/api/tasks", json={
        "title": "Inbox", "estimated_minutes": 40
    }).json()["id"]
    assert client.post(WEEK + "/evaluate", json={
        "task_ids": [task_id]
    }).status_code == 422
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "INBOX"
    assert client.post(WEEK + "/evaluate", json={"task_ids": []}).json()["status"] == "FEASIBLE"
