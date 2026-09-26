from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.db import Base, get_session
from app.infrastructure import models  # noqa: F401
from app.main import app


def test_capture_and_read_inbox_api() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post("/api/tasks", json={"title": "Quick capture"})
            assert response.status_code == 201
            assert response.json()["status"] == "INBOX"

            inbox = client.get("/api/tasks/inbox")
            assert inbox.status_code == 200
            items = inbox.json()
            assert len(items) == 1
            assert items[0]["title"] == "Quick capture"
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
