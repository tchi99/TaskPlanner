"""TP-023A backend contract; the React grid belongs to TP-023B."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.application.weekly_schedule import (
    ExceptionDecision, Section, Slot, WeeklyDraft,
    confirm_weekly, preview_weekly, read_weekly,
)
from app.application.uow import UnitOfWork
from app.domain.recurring_availability import AvailabilityMode, RuleConflict, RuleKind
from app.infrastructure.uow import get_uow
from app.server.recurring_availability import _owner
from app.server.errors import invoke

router = APIRouter(prefix="/api/availability/weekly-schedule",
                   tags=["weekly-schedule"])


class SlotInput(BaseModel):
    starts_at_local: str
    ends_at_local: str
    mode: AvailabilityMode | None = None
    start_fold: int | None = Field(default=None, ge=0, le=1)
    end_fold: int | None = Field(default=None, ge=0, le=1)


class SectionInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    kind: RuleKind
    work_type_id: UUID | None = None
    slots: list[SlotInput] = Field(default_factory=list)


class ExceptionDecisionInput(BaseModel):
    exception_id: UUID
    expected_version: int = Field(ge=1)
    action: str
    target_rule_id: UUID | None = None


class WeeklyDraftInput(BaseModel):
    effective_from: date
    timezone_name: str = Field(min_length=1, max_length=100)
    sections: list[SectionInput] = Field(min_length=1, max_length=100)
    expected_versions: dict[str, int] = Field(default_factory=dict)
    exception_decisions: list[ExceptionDecisionInput] = Field(default_factory=list)

    def to_domain(self) -> WeeklyDraft:
        return WeeklyDraft(
            effective_from=self.effective_from, timezone_name=self.timezone_name,
            sections=tuple(Section(
                weekday=v.weekday, kind=v.kind, work_type_id=v.work_type_id,
                slots=tuple(Slot(**s.model_dump()) for s in v.slots),
            ) for v in self.sections),
            expected_versions=self.expected_versions,
            exception_decisions=tuple(ExceptionDecision(**d.model_dump())
                                      for d in self.exception_decisions),
        )


class ConfirmInput(WeeklyDraftInput):
    command_id: UUID
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: bool
    acknowledge_conflicts: bool = False


def _run(action):
    try:
        return invoke(action)
    except RuleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def read_grid(request: Request, effective_from: date = Query(),
              timezone_name: str = Query(), uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: read_weekly(uow, _owner(request),
                                    effective_from, timezone_name))


@router.post("/preview")
def preview_grid(request: Request, payload: WeeklyDraftInput,
                 uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: preview_weekly(uow, _owner(request), payload.to_domain()))


@router.post("/confirm")
def confirm_grid(request: Request, payload: ConfirmInput,
                 uow: UnitOfWork = Depends(get_uow)):
    return _run(lambda: confirm_weekly(
        uow, _owner(request), payload.to_domain(),
        command_id=payload.command_id, fingerprint=payload.fingerprint,
        confirmed=payload.confirmed,
        acknowledge_conflicts=payload.acknowledge_conflicts,
    ))
