"""TP-022R HTTP entrypoints; local decisions only, no external writes."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.application.booking_resolutions import (
    StaleBookingResolution, confirm_resolution, list_resolution_history,
    preview_resolution,
)
from app.application.calendar import CalendarReader
from app.application.uow import UnitOfWork
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarUnavailable,
)
from app.infrastructure.uow import get_uow
from app.server.calendar import get_calendar_reader
from app.server.errors import invoke
from app.server.recurring_availability import _owner
from app.server.time_blocks import ConfirmedBlockResponse

router = APIRouter(prefix="/api/capacity/weeks", tags=["booking-resolutions"])


class ResolutionSelection(BaseModel):
    decision: Literal["CANCEL", "MOVE", "KEEP"]
    expected_revision: int = Field(ge=1)
    timezone_name: str = "UTC"
    reason: str = Field(min_length=1, max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_replacement(self):
        if self.decision == "MOVE" and (self.starts_at is None or self.ends_at is None):
            raise ValueError("MOVE requires a replacement interval")
        if self.decision != "MOVE" and (self.starts_at is not None or self.ends_at is not None):
            raise ValueError("only MOVE accepts a replacement interval")
        return self


class ConfirmResolution(ResolutionSelection):
    fingerprint: str = Field(min_length=64, max_length=64)
    decision_id: UUID
    confirmed: Literal[True]


def _run(action):
    try:
        return invoke(action)
    except StaleBookingResolution as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GoogleCalendarNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Google Calendar is not configured") from exc
    except GoogleCalendarUnavailable as exc:
        raise HTTPException(status_code=502, detail="Google Calendar is unavailable") from exc


@router.post("/{week_start}/time-blocks/{booking_id}/resolution/preview")
def preview(
    week_start: date, booking_id: UUID, payload: ResolutionSelection,
    request: Request, uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
):
    result = _run(lambda: preview_resolution(
        uow, reader, _owner(request), week_start, booking_id,
        payload.expected_revision, payload.decision, payload.timezone_name,
        payload.reason, payload.starts_at, payload.ends_at,
    ))
    return {
        "state": "PROPOSED", "fingerprint": result.fingerprint,
        "booking": ConfirmedBlockResponse.from_domain(result.booking),
        "decision": result.decision,
        "conflict_codes": result.conflict_codes,
        "calendar_checked": result.calendar_checked,
        "replacement": ({"starts_at": result.replacement.starts_at,
                         "ends_at": result.replacement.ends_at,
                         "week_start": result.replacement.week_start,
                         "task_id": result.replacement.task_id,
                         "segment_id": result.replacement.segment_id,
                         "work_type_id": result.replacement.work_type_id,
                         "transferred_from": result.replacement.transferred_from}
                        if result.replacement else None),
        "consequences": result.consequences, "calendar_written": False,
    }


@router.post("/{week_start}/time-blocks/{booking_id}/resolution/confirm")
def confirm(
    week_start: date, booking_id: UUID, payload: ConfirmResolution,
    request: Request, uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
):
    original, replacement = _run(lambda: confirm_resolution(
        uow, reader, _owner(request), week_start, booking_id,
        payload.expected_revision, payload.decision, payload.timezone_name,
        payload.reason, payload.fingerprint, payload.decision_id,
        payload.starts_at, payload.ends_at,
    ))
    return {
        "state": "CONFIRMED_LOCAL", "decision": payload.decision,
        "decision_id": payload.decision_id, "calendar_written": False,
        "booking": ConfirmedBlockResponse.from_domain(original),
        "replacement": (ConfirmedBlockResponse.from_domain(replacement)
                        if replacement else None),
    }


@router.get("/{week_start}/time-blocks/{booking_id}/resolution/history")
def history(
    week_start: date, booking_id: UUID, request: Request,
    uow: UnitOfWork = Depends(get_uow),
):
    events = _run(lambda: list_resolution_history(
        uow, _owner(request), week_start, booking_id,
    ))
    return [{"id": v.id, "event_type": v.event_type, "occurred_at": v.occurred_at,
             "payload": v.payload} for v in events]
