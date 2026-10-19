from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.domain.calendar import CalendarCommitment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.google_calendar import GoogleCalendarReader, GoogleCalendarUnavailable
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.calendar import get_calendar_reader


WEEK = "/api/capacity/weeks/2026-10-05"


class Reader:
    def __init__(self):
        self.windows = []

    def list_commitments(self, starts_at, ends_at, timezone_name):
        self.windows.append((starts_at, ends_at, timezone_name))
        return [
            CalendarCommitment(
                "primary", "meeting", "Réunion",
                datetime.fromisoformat("2026-10-05T09:30:00-04:00"),
                datetime.fromisoformat("2026-10-05T10:30:00-04:00"),
            ),
        ]


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


def test_invalid_timezone_and_week_rejected_before_external_calls(client):
    reader = Reader()
    app.dependency_overrides[get_calendar_reader] = lambda: reader
    assert client.get(WEEK + "/calendar?timezone_name=Invalid/Place").status_code == 422
    assert client.get("/api/capacity/weeks/2026-10-06/calendar").status_code == 422
    assert reader.windows == []


def test_unconfigured_or_failed_calendar_never_falls_back_to_zero_bookings(client):
    app.dependency_overrides[get_calendar_reader] = lambda: GoogleCalendarReader(
        Settings(
            google_access_token=None, google_refresh_token=None,
            google_client_id=None, google_client_secret=None,
        )
    )
    response = client.get(WEEK + "/calendar")
    assert response.status_code == 503

    class FailingReader:
        def list_commitments(self, starts_at, ends_at, timezone_name):
            raise GoogleCalendarUnavailable("private token details")
    app.dependency_overrides[get_calendar_reader] = lambda: FailingReader()
    response = client.get(WEEK + "/calendar")
    assert response.status_code == 502
    assert "private" not in response.text
