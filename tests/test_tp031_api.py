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


def test_morning_api_reports_facts_and_leaves_persistence_unchanged(runtime):
    client, engine = runtime
    protected = client.post("/api/tasks", json={
        "title": "Urgent", "estimated_minutes": 90,
        "due_at": "2026-10-10T16:00:00Z",
    }).json()["id"]
    flexible = client.post("/api/tasks", json={
        "title": "Souple", "estimated_minutes": 30,
    }).json()["id"]
    inbox = client.post("/api/tasks", json={"title": "Capture"}).json()["id"]
    for task_id in (protected, flexible):
        assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    assert client.patch(f"/api/tasks/{protected}/protection", json={
        "protection": "PROTECTED",
    }).status_code == 200
    assert client.patch(f"/api/tasks/{flexible}/protection", json={
        "protection": "FLEXIBLE", "confirm_downgrade": True,
    }).status_code == 200
    assert client.post("/api/capacity/weeks/2026-10-05/blocks", json={
        "starts_at": "2026-10-10T09:00:00-04:00",
        "ends_at": "2026-10-10T10:00:00-04:00",
    }).status_code == 201
    before = client.get("/api/tasks").json()
    endpoint = "/api/review/morning?day=2026-10-10&timezone_name=America/Toronto"
    result = client.get(endpoint)
    assert result.status_code == 200, result.text
    review = result.json()
    assert review["is_hypothetical"] is True
    assert review["has_daily_assignments"] is False
    assert review["today_available_minutes"] == 60
    assert review["weekly_if_all_open"]["known_demand_minutes"] == 120
    assert review["weekly_if_all_open"]["status"] == "OVER_CAPACITY"
    assert review["inbox_count"] == 1
    assert [item["task_id"] for item in review["must_review"]] == [protected]
    assert [item["task_id"] for item in review["may_slip"]] == [flexible]
    assert review["must_review"][0]["due_status"] == "TODAY"
    assert review["decisions"][-1]["code"] == "SELECT_TODAY"
    assert client.get(endpoint).json() == review
    assert client.get("/api/tasks").json() == before
    assert client.get(f"/api/tasks/{inbox}").json()["status"] == "INBOX"
    with Session(engine) as session:
        assert len(session.scalars(select(TaskRecord)).all()) == 3


def test_morning_empty_and_validation(runtime):
    client, _ = runtime
    url = "/api/review/morning?day=2026-10-10&timezone_name=America/Toronto"
    response = client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["open_task_count"] == 0
    assert data["must_review"] == []
    assert data["may_slip"] == []
    assert data["manual_block_count"] == 0
    assert client.get("/api/review/morning?day=invalid").status_code == 422
    assert client.get("/api/review/morning?day=2026-10-10&timezone_name=Bad/Zone").status_code == 422
