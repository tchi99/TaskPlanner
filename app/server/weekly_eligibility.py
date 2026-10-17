"""TP-025C: read-only scope/week eligibility display API."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.application.calendar import CalendarReader
from app.application.uow import UnitOfWork
from app.application.weekly_eligibility import weekly_eligibility
from app.infrastructure.uow import get_uow
from app.server.calendar import get_calendar_reader
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/availability", tags=["weekly-eligibility"])


@router.get("/eligibility-week")
def read_week(
    request: Request,
    week_start: date = Query(),
    timezone_name: str = Query(),
    scope_id: UUID | None = Query(default=None),
    uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
):
    """Does not reserve time, write to Google, or assert unchecked time is free."""
    return invoke(lambda: weekly_eligibility(
        uow, reader, _owner(request), week_start, timezone_name, scope_id))
