"""Optional server-side Google Calendar read-only adapter (no calendar writes)."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, time
from typing import Any, Mapping
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import Settings
from app.domain.calendar import CalendarCommitment


class GoogleCalendarUnavailable(Exception):
    """Provider request failed; do not claim calendar-adjusted capacity."""


class GoogleCalendarNotConfigured(GoogleCalendarUnavailable):
    """No server-side read credential is configured."""


def _moment(value: Mapping[str, Any], fallback_timezone: str) -> datetime:
    if "dateTime" in value:
        parsed = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
        # Google may supply a separate timeZone on an exceptional event.
        return parsed.replace(tzinfo=ZoneInfo(str(value.get("timeZone") or fallback_timezone)))
    return datetime.combine(
        datetime.strptime(str(value["date"]), "%Y-%m-%d").date(),
        time.min, tzinfo=ZoneInfo(fallback_timezone),
    )


class GoogleCalendarReader:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client

    def _access_token(self, client: httpx.Client) -> str:
        config = self._settings
        if config.google_access_token:
            return config.google_access_token.get_secret_value()
        if not (config.google_refresh_token and config.google_client_id and config.google_client_secret):
            raise GoogleCalendarNotConfigured("Google Calendar read credential not configured")
        response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret.get_secret_value(),
                "refresh_token": config.google_refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise GoogleCalendarUnavailable("Google Calendar authentication unavailable")
        return token

    def list_commitments(
        self, starts_at: datetime, ends_at: datetime, timezone_name: str
    ) -> tuple[CalendarCommitment, ...]:
        # Missing credentials must not be interpreted as an empty calendar.
        try:
            ZoneInfo(timezone_name)
            if starts_at.tzinfo is None or ends_at.tzinfo is None:
                raise ValueError("calendar query boundaries must be timezone-aware")
            with (nullcontext(self._client) if self._client is not None else httpx.Client(timeout=10.0)) as client:
                token = self._access_token(client)
                calendars = [
                    value.strip() for value in self._settings.google_calendar_ids.split(",")
                    if value.strip()
                ]
                if not calendars:
                    raise GoogleCalendarNotConfigured("No Google Calendar selected")
                result: list[CalendarCommitment] = []
                for calendar_id in dict.fromkeys(calendars):
                    page: str | None = None
                    seen: set[str] = set()
                    while True:
                        params = {
                            "timeMin": starts_at.isoformat(),
                            "timeMax": ends_at.isoformat(),
                            "singleEvents": "true",
                            "orderBy": "startTime",
                            "showDeleted": "false",
                            "maxResults": "2500",
                        }
                        if page:
                            params["pageToken"] = page
                        response = client.get(
                            "https://www.googleapis.com/calendar/v3/calendars/"
                            + quote(calendar_id, safe="") + "/events",
                            params=params,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        response.raise_for_status()
                        body = response.json()
                        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                            raise GoogleCalendarUnavailable("Invalid Google Calendar response")
                        for event in body["items"]:
                            if not isinstance(event, dict) or (
                                event.get("status") == "cancelled"
                                or event.get("transparency") == "transparent"
                                or event.get("eventType") == "workingLocation"
                                or any(
                                    guest.get("self") and guest.get("responseStatus") == "declined"
                                    for guest in event.get("attendees", [])
                                    if isinstance(guest, dict)
                                )
                            ):
                                continue
                            try:
                                start = _moment(event["start"], timezone_name)
                                end = _moment(event["end"], timezone_name)
                                commitment = CalendarCommitment(
                                    calendar_id=calendar_id,
                                    event_id=str(event["id"]),
                                    title=str(event.get("summary") or "Occupé"),
                                    starts_at=start, ends_at=end,
                                )
                            except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
                                raise GoogleCalendarUnavailable("Invalid Google Calendar event") from exc
                            if commitment.starts_at < ends_at and commitment.ends_at > starts_at:
                                result.append(commitment)
                        next_page = body.get("nextPageToken")
                        if not next_page:
                            break
                        if not isinstance(next_page, str) or next_page in seen:
                            raise GoogleCalendarUnavailable("Invalid Google Calendar pagination")
                        seen.add(next_page)
                        page = next_page
                return tuple(result)
        except GoogleCalendarUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Never include provider bodies or credentials in client-facing errors.
            raise GoogleCalendarUnavailable("Google Calendar is temporarily unavailable") from exc
