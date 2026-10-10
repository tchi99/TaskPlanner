from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, TaskSegmentRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def test_task_segment_override_history_and_displacement_preview(runtime):
    client, engine = runtime
    task = client.post("/api/tasks", json={"title": "Important", "estimated_minutes": 60,
        "due_at": "2026-10-12T12:00:00Z"}).json()
    task_id = task["id"]
    assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    assert client.patch(f"/api/tasks/{task_id}/protection", json={
        "protection": "PROTECTED"
    }).json()["protection"] == "PROTECTED"
    response = client.post(f"/api/tasks/{task_id}/segments", json={
        "title": "Segment", "protection_override": "FLEXIBLE",
        "estimated_minutes": 30
    })
    assert response.status_code == 201, response.text
    segment = response.json()["segments"][0]
    segment_id = segment["id"]
    assert segment["protection_override"] == "FLEXIBLE"
    assert segment["effective_protection"] == "PROTECTED"
    result = client.patch(f"/api/tasks/{task_id}/segments/{segment_id}", json={
        "protection_override": "PROTECTED"
    })
    assert result.status_code == 200, result.text
    assert client.patch(f"/api/tasks/{task_id}/segments/{segment_id}", json={
        "protection_override": "PROTECTED"
    }).status_code == 200
    assert client.patch(f"/api/tasks/{task_id}/segments/{segment_id}", json={
        "protection_override": "INVALID"
    }).status_code == 422

    preview = client.post(f"/api/tasks/{task_id}/displacement-preview", json={
        "segment_id": segment_id,
        "original_at": "2026-10-11T08:00:00Z",
        "proposed_at": "2026-10-13T08:00:00Z",
    })
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["reason_code"] == "PROTECTED_COMMITMENT"
    assert body["deadline_crossed"] is True
    assert body["confirmation_required"] is True
    assert client.post(f"/api/tasks/{task_id}/displacement-preview", json={
        "original_at": "2026-10-11T08:00:00",
        "proposed_at": "2026-10-13T08:00:00Z",
    }).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/displacement-preview", json={
        "segment_id": str(uuid4()),
        "original_at": "2026-10-11T08:00:00Z",
        "proposed_at": "2026-10-13T08:00:00Z",
    }).status_code == 422
    assert client.get(f"/api/tasks/{task_id}").json()["due_at"] is not None
    with Session(engine) as session:
        record = session.get(TaskSegmentRecord, segment_id)
        assert record.protection_override == "PROTECTED"
        events = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.task_id == task_id,
        ).order_by(HistoryEventRecord.sequence)).all()
        kinds = [item.event_type for item in events]
        assert kinds.count("TASK_PROTECTION_CHANGED") == 1
        assert kinds.count("SEGMENT_PROTECTION_CHANGED") == 1
        assert events[-1].payload == {"before": "FLEXIBLE", "after": "PROTECTED"}
        assert events[-1].source == "USER"


def test_nonexistent_task_and_no_mutations_for_preview(runtime):
    client, _ = runtime
    assert client.patch(f"/api/tasks/{uuid4()}/protection", json={
        "protection": "FLEXIBLE"
    }).status_code == 404
    task_id = client.post("/api/tasks", json={"title": "Inbox"}).json()["id"]
    path = f"/api/tasks/{task_id}/displacement-preview"
    preview = {"original_at": "2026-10-11T08:00:00Z",
        "proposed_at": "2026-10-12T08:00:00Z"}
    assert client.post(path, json=preview).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    assert client.post(path, json=preview).status_code == 200
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "TODO"
