"""Read-only physical envelopes and occurrences; mutations use weekly preview/confirm."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.application.recurring_availability import get_rule, list_rules, read_occurrences
from app.application.uow import UnitOfWork
from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleConflict, RuleKind,
)
from app.infrastructure.uow import get_uow
from app.server.errors import invoke


router = APIRouter(prefix="/api/availability/rules", tags=["recurring-availability"])


def _owner(request: Request) -> str:
    if request.app.state.security_settings.auth_mode == "local":
        return "urn:taskplanner:local"
    return request.state.user_id


def _run(action):
    try:
        return invoke(action)
    except RuleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class RevisionResponse(BaseModel):
    number: int
    effective_from: date
    valid_until: date | None = None
    timezone_name: str
    days_of_week: tuple[int, ...]
    starts_at_local: str
    ends_at_local: str
    kind: RuleKind
    work_type_id: UUID | None = None
    mode: AvailabilityMode | None = None
    enabled: bool = True
    start_fold: int | None = None
    end_fold: int | None = None
    supersedes_future: bool = False


class RuleResponse(BaseModel):
    id: UUID
    version: int
    revisions: list[RevisionResponse]

    @classmethod
    def from_domain(cls, value: RecurringAvailabilityRule) -> "RuleResponse":
        return cls(
            id=value.id, version=value.version,
            revisions=[RevisionResponse(
                number=rev.number, effective_from=rev.effective_from,
                valid_until=rev.valid_until, timezone_name=rev.timezone_name,
                days_of_week=rev.days_of_week, starts_at_local=rev.starts_at_local,
                ends_at_local=rev.ends_at_local, kind=rev.kind,
                work_type_id=rev.work_type_id, mode=rev.mode,
                enabled=rev.enabled, start_fold=rev.start_fold, end_fold=rev.end_fold,
                supersedes_future=rev.supersedes_future,
            ) for rev in value.revisions],
        )


class OccurrenceResponse(BaseModel):
    rule_id: UUID
    revision: int
    original_local_date: date
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None
    kind: RuleKind
    mode: AvailabilityMode | None


class ExpansionIssueResponse(BaseModel):
    rule_id: UUID
    revision: int
    original_local_date: date
    reason: str


class RawOccurrencesResponse(BaseModel):
    projection: str = "RAW_DECLARATIONS_NOT_FREE_CAPACITY"
    occurrences: list[OccurrenceResponse]
    issues: list[ExpansionIssueResponse]


@router.get("/occurrences", response_model=RawOccurrencesResponse)
def occurrences(
    request: Request,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    uow: UnitOfWork = Depends(get_uow),
) -> RawOccurrencesResponse:
    found, issues = _run(lambda: read_occurrences(
        uow, _owner(request), from_date, to_date
    ))
    return RawOccurrencesResponse(
        occurrences=[OccurrenceResponse(**vars_for_occurrence(v)) for v in found],
        issues=[ExpansionIssueResponse(
            rule_id=v.rule_id, revision=v.revision,
            original_local_date=v.original_local_date, reason=v.reason,
        ) for v in issues],
    )


def vars_for_occurrence(value) -> dict:
    return {
        "rule_id": value.rule_id, "revision": value.revision,
        "original_local_date": value.original_local_date,
        "starts_at": value.starts_at, "ends_at": value.ends_at,
        "work_type_id": value.work_type_id, "kind": value.kind, "mode": value.mode,
    }


@router.get("", response_model=list[RuleResponse])
def all_rules(request: Request, uow: UnitOfWork = Depends(get_uow)) -> list[RuleResponse]:
    return [RuleResponse.from_domain(value)
            for value in _run(lambda: list_rules(uow, _owner(request)))]


@router.get("/{rule_id}", response_model=RuleResponse)
def one_rule(
    rule_id: UUID, request: Request, uow: UnitOfWork = Depends(get_uow),
) -> RuleResponse:
    return RuleResponse.from_domain(_run(lambda: get_rule(
        uow, _owner(request), rule_id,
    )))


