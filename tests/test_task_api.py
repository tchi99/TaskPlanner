from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


def _test_uow_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, lambda: SqlAlchemyUnitOfWork(session_factory)


def test_capture_and_read_inbox_api() -> None:
    engine, uow_factory = _test_uow_factory()
    app.dependency_overrides[get_uow] = uow_factory
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/tasks",
                json={"title": "  Quick capture  "},
            )
            assert response.status_code == 201
            assert response.json()["status"] == "INBOX"
            assert response.json()["title"] == "Quick capture"

            inbox = client.get("/api/tasks/inbox")
            assert inbox.status_code == 200
            items = inbox.json()
            assert len(items) == 1
            assert items[0]["title"] == "Quick capture"

        with Session(engine) as session:
            events = session.scalars(select(HistoryEventRecord)).all()
            assert [event.event_type for event in events] == ["TASK_CAPTURED"]
    finally:
        app.dependency_overrides.clear()


def test_inbox_read_does_not_create_history() -> None:
    engine, uow_factory = _test_uow_factory()
    app.dependency_overrides[get_uow] = uow_factory
    try:
        with TestClient(app) as client:
            assert client.post("/api/tasks", json={"title": "One"}).status_code == 201
            assert client.get("/api/tasks/inbox").status_code == 200
            assert client.get("/api/tasks/inbox").status_code == 200

        with Session(engine) as session:
            events = session.scalars(select(HistoryEventRecord)).all()
            assert len(events) == 1
            assert events[0].event_type == "TASK_CAPTURED"
    finally:
        app.dependency_overrides.clear()


def test_capture_rejects_naive_due_date() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "title": "Invalid date",
                "due_at": "2026-09-28T13:00:00",
            },
        )

    assert response.status_code == 422


def test_capture_rejects_blank_title_and_non_positive_estimate() -> None:
    with TestClient(app) as client:
        blank = client.post("/api/tasks", json={"title": "   "})
        invalid_estimate = client.post(
            "/api/tasks",
            json={"title": "Estimate", "estimated_minutes": 0},
        )

    assert blank.status_code == 422
    assert invalid_estimate.status_code == 422
