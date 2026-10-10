"""Read-only Google Calendar projection; no local or external mutations."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.calendar import CalendarReader, CalendarWeek, read_calendar_week
from app.application.uow import UnitOfWork
from app.config import get_settings
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarReader, GoogleCalendarUnavailable,
)
from app.infrastructure.uow import get_uow
from app.server.errors import invoke


router = APIRouter(prefix="/api/capacity/weeks", tags=["calendar"])


def get_calendar_reader() -> CalendarReader:
    return GoogleCalendarReader(get_settings())


class CalendarEventResponse(BaseModel):
    calendar_id: str
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime


class CalendarBucketResponse(BaseModel):
    work_type_id: UUID | None
    manual_available_minutes: int
    occupied_minutes: int
    remaining_minutes: int


class CalendarWeekResponse(BaseModel):
    week_start: date
    timezone_name: str
    source: str = "GOOGLE_CALENDAR"
    is_read_only: bool = True
    manual_available_minutes: int
    occupied_minutes: int
    remaining_minutes: int
    by_work_type: list[CalendarBucketResponse]
    commitments: list[CalendarEventResponse]

    @classmethod
    def from_domain(cls, value: CalendarWeek) -> "CalendarWeekResponse":
        cap = value.capacity
        return cls(
            week_start=cap.week_start, timezone_name=value.timezone_name,
            manual_available_minutes=cap.manual_available_minutes,
            occupied_minutes=cap.occupied_minutes,
            remaining_minutes=cap.remaining_minutes,
            by_work_type=[
                CalendarBucketResponse(
                    work_type_id=item.work_type_id,
                    manual_available_minutes=item.manual_available_minutes,
                    occupied_minutes=item.occupied_minutes,
                    remaining_minutes=item.remaining_minutes,
                ) for item in cap.by_work_type
            ],
            commitments=[
                CalendarEventResponse(
                    calendar_id=event.calendar_id, event_id=event.event_id,
                    title=event.title, starts_at=event.starts_at, ends_at=event.ends_at,
                ) for event in value.commitments
            ],
        )


@router.get("/{week_start}/calendar", response_model=CalendarWeekResponse)
def get_calendar_week(
    week_start: date,
    timezone_name: str = "UTC",
    uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
) -> CalendarWeekResponse:
    try:
        return CalendarWeekResponse.from_domain(invoke(
            lambda: read_calendar_week(uow, reader, week_start, timezone_name)
        ))
    except GoogleCalendarNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Google Calendar is not configured") from exc
    except GoogleCalendarUnavailable as exc:
        raise HTTPException(status_code=502, detail="Google Calendar is unavailable") from exc
