"""Time-block preview and explicit local confirmation; Google Calendar stays read-only."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.application.calendar import CalendarReader
from app.application.time_blocks import (
    StaleTimeBlockProposal, list_confirmed_time_blocks, preview_time_blocks,
)
from app.application.uow import UnitOfWork
from app.domain.time_blocks import ConfirmedTimeBlock, TimeBlockPreview
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarUnavailable,
)
from app.infrastructure.uow import get_uow
from app.server.calendar import get_calendar_reader
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/capacity/weeks", tags=["time-blocks"])


class TimeBlockSelection(BaseModel):
    task_ids: list[UUID]
    timezone_name: str = "UTC"
    offer_transfers: bool = False


class ConfirmTimeBlocks(TimeBlockSelection):
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: Literal[True]
    accept_transfers: bool = False


class SuggestedBlockResponse(BaseModel):
    task_id: UUID
    segment_id: UUID | None
    label: str
    work_type_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    minutes: int
    transferred_from: UUID | None = None


class UnplacedResponse(BaseModel):
    task_id: UUID
    segment_id: UUID | None
    label: str
    remaining_minutes: int | None
    reason: str


class ConfirmedBlockResponse(BaseModel):
    id: UUID
    task_id: UUID
    segment_id: UUID | None
    work_type_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    transferred_from: UUID | None = None
    status: str = "CONFIRMED"
    revision: int = 1

    @classmethod
    def from_domain(cls, block: ConfirmedTimeBlock) -> "ConfirmedBlockResponse":
        return cls(
            id=block.id, task_id=block.task_id, segment_id=block.segment_id,
            work_type_id=block.work_type_id, starts_at=block.starts_at,
            ends_at=block.ends_at, transferred_from=block.transferred_from,
            status=block.status, revision=block.revision,
        )


class TimeBlockPreviewResponse(BaseModel):
    week_start: date
    timezone_name: str
    task_ids: list[UUID]
    fingerprint: str
    state: str = "PROPOSED"
    can_confirm: bool
    requires_transfer_confirmation: bool = False
    transfer_consequences: list[str] = []
    calendar_checked: bool = True
    destinations: str = "TASKPLANNER_LOCAL_ONLY"
    suggestions: list[SuggestedBlockResponse]
    unplaced: list[UnplacedResponse]

    @classmethod
    def from_domain(cls, proposal: TimeBlockPreview) -> "TimeBlockPreviewResponse":
        return cls(
            week_start=proposal.week_start, timezone_name=proposal.timezone_name,
            task_ids=list(proposal.task_ids), fingerprint=proposal.fingerprint,
            can_confirm=proposal.can_confirm,
            requires_transfer_confirmation=proposal.requires_transfer_confirmation,
            transfer_consequences=[
                f"Réaffecter {s.minutes} minutes PREFERRED du type "
                f"{s.transferred_from} au type {s.work_type_id}; "
                "le temps libre du type donneur diminue sans modifier ses réservations."
                for s in proposal.suggestions if s.transferred_from is not None
            ],
            suggestions=[SuggestedBlockResponse(**{
                "task_id": s.task_id, "segment_id": s.segment_id, "label": s.label,
                "work_type_id": s.work_type_id, "starts_at": s.starts_at,
                "ends_at": s.ends_at, "minutes": s.minutes,
                "transferred_from": s.transferred_from,
            }) for s in proposal.suggestions],
            unplaced=[UnplacedResponse(**{
                "task_id": u.task_id, "segment_id": u.segment_id, "label": u.label,
                "remaining_minutes": u.remaining_minutes, "reason": u.reason,
            }) for u in proposal.unplaced],
        )


class ConfirmationResponse(BaseModel):
    state: str = "CONFIRMED_LOCAL"
    calendar_written: bool = False
    blocks: list[ConfirmedBlockResponse]


def _run(action):
    try:
        return invoke(action)
    except StaleTimeBlockProposal as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GoogleCalendarNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Google Calendar is not configured") from exc
    except GoogleCalendarUnavailable as exc:
        raise HTTPException(status_code=502, detail="Google Calendar is unavailable") from exc


@router.post("/{week_start}/time-blocks/preview", response_model=TimeBlockPreviewResponse)
def preview(
    week_start: date, payload: TimeBlockSelection, request: Request,
    uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
) -> TimeBlockPreviewResponse:
    value, _ = _run(lambda: preview_time_blocks(
        uow, reader, week_start, payload.timezone_name, payload.task_ids,
        owner_id=_owner(request), offer_transfers=payload.offer_transfers,
    ))
    return TimeBlockPreviewResponse.from_domain(value)


@router.post("/{week_start}/time-blocks/confirm", response_model=ConfirmationResponse)
def confirm(
    week_start: date, payload: ConfirmTimeBlocks, request: Request,
    uow: UnitOfWork = Depends(get_uow),
    reader: CalendarReader = Depends(get_calendar_reader),
) -> ConfirmationResponse:
    _, blocks = _run(lambda: preview_time_blocks(
        uow, reader, week_start, payload.timezone_name, payload.task_ids,
        expected_fingerprint=payload.fingerprint, confirm=True,
        owner_id=_owner(request), offer_transfers=payload.offer_transfers,
        accept_transfers=payload.accept_transfers,
    ))
    return ConfirmationResponse(blocks=[
        ConfirmedBlockResponse.from_domain(block) for block in blocks
    ])


@router.get("/{week_start}/time-blocks", response_model=list[ConfirmedBlockResponse])
def list_confirmed(
    week_start: date, uow: UnitOfWork = Depends(get_uow),
) -> list[ConfirmedBlockResponse]:
    return [ConfirmedBlockResponse.from_domain(block) for block in invoke(
        lambda: list_confirmed_time_blocks(uow, week_start)
    )]
