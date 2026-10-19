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


def test_proposal_validation_and_missing_task(runtime):
    client, _ = runtime
    id_ = str(uuid4())
    assert client.post(WEEK + "/proposals", json={"task_ids": [id_]}).status_code == 404
    assert client.post(WEEK + "/proposals", json={"task_ids": [id_, id_]}).status_code == 422
    assert client.post("/api/capacity/weeks/2026-10-06/proposals", json={"task_ids": []}).status_code == 422
    task_id = client.post("/api/tasks", json={"title": "Inbox"}).json()["id"]
    assert client.post(WEEK + "/proposals", json={"task_ids": [task_id]}).status_code == 422
    assert client.post(WEEK + "/proposals", json={"task_ids": []}).json()["options"][0]["kind"] == "KEEP"
