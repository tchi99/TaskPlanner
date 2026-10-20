"""TP-025D owner-scoped contextual edition (not a Google Calendar mutation)."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.application.eligibility_edits import (
    EligibilityDraft, EligibilityExceptionDecision, read_series, preview_edit, confirm_edit,
)
from app.application.eligibility_dated import (
    DatedPermissionDraft, preview_dated, confirm_dated,
)
from app.domain.eligibility import EligibilityAction
from app.application.uow import UnitOfWork
from app.domain.eligibility import EligibilityConflict
from app.domain.recurring_availability import RuleConflict
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/availability/eligibility-edits",
                   tags=["eligibility-edits"])


class ExceptionDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exception_id: UUID
    expected_version: int = Field(ge=1)
    action: str


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
    target_days_of_week: tuple[int, ...] | None = None
    exception_decisions: tuple[ExceptionDecisionInput, ...] = ()

    def domain(self) -> EligibilityDraft:
        data = {name: getattr(self, name) for name in DraftInput.model_fields}
        data["exception_decisions"] = tuple(
            EligibilityExceptionDecision(**decision.model_dump())
            for decision in self.exception_decisions
        )
        return EligibilityDraft(**data)


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


class DatedPermissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    series_id: UUID
    exception_id: UUID | None = None
    expected_version: int = Field(ge=0)
    original_local_date: date
    timezone_name: str = Field(min_length=1, max_length=100)
    action: EligibilityAction
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool = True

    def domain(self) -> DatedPermissionDraft:
        return DatedPermissionDraft(**self.model_dump())


class DatedPermissionConfirmation(DatedPermissionInput):
    command_id: UUID
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: bool
    acknowledge_bookings: bool = False


@router.post("/exceptions/preview")
def preview_exception(request: Request, body: DatedPermissionInput,
                      uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: preview_dated(uow, _owner(request), body.domain()))


@router.post("/exceptions/confirm")
def confirm_exception(request: Request, body: DatedPermissionConfirmation,
                      uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: confirm_dated(
        uow, _owner(request), body.domain(), command_id=body.command_id,
        fingerprint=body.fingerprint, confirmed=body.confirmed,
        acknowledge_bookings=body.acknowledge_bookings,
    ))
