"""TP-025D owner-scoped contextual edition (not a Google Calendar mutation)."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.application.eligibility_edits import (
    EligibilityDraft, read_series, preview_edit, confirm_edit,
)
from app.application.uow import UnitOfWork
from app.domain.eligibility import EligibilityConflict
from app.domain.recurring_availability import RuleConflict
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/availability/eligibility-edits",
                   tags=["eligibility-edits"])


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    series_id: UUID | None = None
    scope_id: UUID
    work_type_id: UUID
    expected_version: int = Field(ge=0)
    effective_from: date
    timezone_name: str = Field(min_length=1, max_length=100)
    days_of_week: tuple[int, ...]
    starts_at_local: str
    ends_at_local: str
    priority_rank: int | None = Field(default=None, ge=1)
    enabled: bool = True
    start_fold: int | None = Field(default=None, ge=0, le=1)
    end_fold: int | None = Field(default=None, ge=0, le=1)

    def domain(self) -> EligibilityDraft:
        return EligibilityDraft(**{name: getattr(self, name) for name in DraftInput.model_fields})


class Confirmation(DraftInput):
    command_id: UUID
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: bool
    acknowledge_bookings: bool = False


def _run(action):
    try:
        return invoke(action)
    except (RuleConflict, EligibilityConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/series/{series_id}")
def series(series_id: UUID, request: Request, uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: read_series(uow, _owner(request), series_id))


@router.post("/preview")
def preview(request: Request, body: DraftInput,
            uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: preview_edit(uow, _owner(request), body.domain()))


@router.post("/confirm")
def confirm(request: Request, body: Confirmation,
            uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: confirm_edit(
        uow, _owner(request), body.domain(), command_id=body.command_id,
        fingerprint=body.fingerprint, confirmed=body.confirmed,
        acknowledge_bookings=body.acknowledge_bookings,
    ))
