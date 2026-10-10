"""Google Calendar adapter contract: offline, read-only, paginated, fail-closed."""
from datetime import datetime
from urllib.parse import unquote

import httpx
import pytest

from app.config import Settings
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarReader, GoogleCalendarUnavailable,
)


START = datetime.fromisoformat("2026-10-05T00:00:00-04:00")
END = datetime.fromisoformat("2026-10-12T00:00:00-04:00")


def test_busy_events_across_pages_calendars_and_all_day_are_normalized():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer test-only"
        assert request.url.params["singleEvents"] == "true"
        assert request.url.params["timeMin"] == START.isoformat()
        calendar = unquote(request.url.path.split("/calendars/")[1].split("/events")[0])
        if calendar == "primary" and "pageToken" not in request.url.params:
            return httpx.Response(200, json={
                "items": [
                    {"id": "busy", "summary": "Réunion",
                     "start": {"dateTime": "2026-10-05T09:00:00-04:00"},
                     "end": {"dateTime": "2026-10-05T10:00:00-04:00"}},
                    {"id": "transparent", "transparency": "transparent",
                     "start": {"dateTime": "2026-10-05T11:00:00-04:00"},
                     "end": {"dateTime": "2026-10-05T12:00:00-04:00"}},
                    {"id": "declined", "attendees": [
                        {"self": True, "responseStatus": "declined"}
                    ], "start": {"date": "2026-10-05"},
                       "end": {"date": "2026-10-06"}},
                ],
                "nextPageToken": "next",
            })
        if calendar == "primary":
            return httpx.Response(200, json={"items": [
                {"id": "all-day", "start": {"date": "2026-10-06"},
                 "end": {"date": "2026-10-07"}},
                {"id": "location", "eventType": "workingLocation",
                 "start": {"date": "2026-10-07"},
                 "end": {"date": "2026-10-08"}},
            ]})
        return httpx.Response(200, json={"items": [
            {"id": "focus", "eventType": "focusTime",
             "start": {"dateTime": "2026-10-05T09:30:00-04:00"},
             "end": {"dateTime": "2026-10-05T10:30:00-04:00"}},
        ]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reader = GoogleCalendarReader(Settings(
            google_access_token="test-only", google_calendar_ids="primary,secondary"
        ), client)
        result = reader.list_commitments(START, END, "America/Toronto")

    assert len(calls) == 3
    assert {event.event_id for event in result} == {"busy", "all-day", "focus"}
    all_day = next(event for event in result if event.event_id == "all-day")
    assert all_day.title == "Occupé"
    assert all_day.starts_at.isoformat() == "2026-10-06T00:00:00-04:00"
    assert all_day.ends_at.isoformat() == "2026-10-07T00:00:00-04:00"


def test_refresh_token_uses_server_side_token_exchange():
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            assert request.url.path == "/token"
            assert "refresh_token=refresh-only" in request.content.decode()
            return httpx.Response(200, json={"access_token": "fresh"})
        assert request.headers["Authorization"] == "Bearer fresh"
        return httpx.Response(200, json={"items": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reader = GoogleCalendarReader(Settings(
            google_access_token=None,
            google_refresh_token="refresh-only",
            google_client_id="id", google_client_secret="secret-only",
        ), client)
        assert reader.list_commitments(START, END, "America/Toronto") == ()
    assert methods == ["POST", "GET"]


def test_missing_credentials_and_provider_errors_are_not_empty_calendar():
    reader = GoogleCalendarReader(Settings(
        google_access_token=None, google_refresh_token=None,
        google_client_id=None, google_client_secret=None,
    ))
    with pytest.raises(GoogleCalendarNotConfigured):
        reader.list_commitments(START, END, "America/Toronto")

    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "bad-secret"})
    )) as client:
        reader = GoogleCalendarReader(Settings(google_access_token="invalid"), client)
        with pytest.raises(GoogleCalendarUnavailable, match="temporarily"):
            reader.list_commitments(START, END, "America/Toronto")


def test_malformed_event_and_pagination_fail_closed():
    for payload in [
        {"items": [{"id": "invalid", "start": {"date": "2026-10-05"}}]},
        {"items": [], "nextPageToken": "same"},
    ]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            reader = GoogleCalendarReader(Settings(google_access_token="test"), client)
            with pytest.raises(GoogleCalendarUnavailable):
                reader.list_commitments(START, END, "America/Toronto")


def test_does_not_use_write_methods_to_calendar():
    operations = []
    def handler(request: httpx.Request) -> httpx.Response:
        operations.append(request.method)
        return httpx.Response(200, json={"items": []})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        GoogleCalendarReader(Settings(google_access_token="test"), client).list_commitments(
            START, END, "America/Toronto"
        )
    assert operations == ["GET"]
