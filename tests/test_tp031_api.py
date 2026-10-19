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
