"""TP-022B API: declared effective projection and previewed exception mutations."""
from datetime import date, datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from app.application.effective_availability import (
    get_exception, list_exceptions, preview_exception, read_effective, save_exception,
)
from app.application.uow import UnitOfWork
from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.recurring_availability import AvailabilityMode, RuleConflict, RuleKind
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/availability", tags=["effective-availability"])


def _run(action):
    try:
        return invoke(action)
    except RuleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class ExceptionSettings(BaseModel):
    action: ExceptionAction
    rule_id: UUID | None = None
    original_local_date: date | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone_name: str = "UTC"
    kind: RuleKind | None = None
    work_type_id: UUID | None = None
    mode: AvailabilityMode | None = None
    enabled: bool = True
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def default_categorized_mode(self):
        if self.kind is RuleKind.CATEGORIZED and self.mode is None:
            self.mode = AvailabilityMode.PREFERRED
        return self

    def fields(self):
        return self.model_dump()


class PreviewRequest(ExceptionSettings):
    exception_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)


class ApplyRequest(ExceptionSettings):
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    acknowledge_conflicts: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class ExceptionResponse(ExceptionSettings):
    id: UUID
    version: int
    owner_id: str

    @classmethod
    def from_domain(cls, value: AvailabilityException):
        return cls(**{key: getattr(value, key) for key in cls.model_fields})


def _projection(value):
    return {
        "projection": "DECLARED_NOT_CALENDAR_VERIFIED",
        "declared_minutes": value.declared_minutes,
        "blocks": [
            {"id": v.id, "starts_at": v.starts_at, "ends_at": v.ends_at,
             "work_type_id": v.work_type_id, "mode": v.mode,
             "sources": v.sources, "minutes": v.minutes}
            for v in value.blocks
        ],
        "issues": [
            {"code": v.code, "starts_at": v.starts_at, "ends_at": v.ends_at,
             "sources": v.sources, "booking_id": v.booking_id, "state": v.state}
            for v in value.issues
        ],
        "expansion_issues": [
            {"rule_id": v.rule_id, "revision": v.revision,
             "original_local_date": v.original_local_date, "reason": v.reason}
            for v in value.expansion_issues
        ],
    }


@router.get("/effective")
def effective(
    request: Request, from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"), timezone_name: str = Query(),
    uow: UnitOfWork = Depends(get_uow),
):
    return _projection(_run(lambda: read_effective(
        uow, _owner(request), from_date, to_date, timezone_name,
    )))


@router.post("/exceptions/preview")
def preview(request: Request, payload: PreviewRequest, uow: UnitOfWork = Depends(get_uow)):
    fields = payload.fields()
    fields.pop("exception_id")
    fields.pop("expected_version")
    fingerprint, projection, window = _run(lambda: preview_exception(
        uow, _owner(request), fields, exception_id=payload.exception_id,
        expected_version=payload.expected_version,
    ))
    return {"fingerprint": fingerprint, "from": window[0], "to": window[1],
            **_projection(projection)}


@router.get("/exceptions", response_model=list[ExceptionResponse])
def all_exceptions(request: Request, uow: UnitOfWork = Depends(get_uow)):
    return [ExceptionResponse.from_domain(value) for value in
            _run(lambda: list_exceptions(uow, _owner(request)))]


@router.post("/exceptions", response_model=ExceptionResponse, status_code=201)
def create_exception(request: Request, payload: ApplyRequest, uow: UnitOfWork = Depends(get_uow)):
    fields = payload.fields()
    for key in ("expected_fingerprint", "acknowledge_conflicts", "expected_version"):
        fields.pop(key)
    if payload.expected_version is not None:
        raise HTTPException(status_code=422, detail="new exception cannot specify expected_version")
    return ExceptionResponse.from_domain(_run(lambda: save_exception(
        uow, _owner(request), fields, payload.expected_fingerprint,
        payload.acknowledge_conflicts,
    )))


@router.get("/exceptions/{exception_id}", response_model=ExceptionResponse)
def one_exception(exception_id: UUID, request: Request, uow: UnitOfWork = Depends(get_uow)):
    return ExceptionResponse.from_domain(_run(lambda: get_exception(
        uow, _owner(request), exception_id,
    )))


@router.patch("/exceptions/{exception_id}", response_model=ExceptionResponse)
def modify_exception(
    exception_id: UUID, request: Request, payload: ApplyRequest,
    uow: UnitOfWork = Depends(get_uow),
):
    if payload.expected_version is None:
        raise HTTPException(status_code=422, detail="expected_version is required")
    fields = payload.fields()
    for key in ("expected_fingerprint", "acknowledge_conflicts", "expected_version"):
        fields.pop(key)
    return ExceptionResponse.from_domain(_run(lambda: save_exception(
        uow, _owner(request), fields, payload.expected_fingerprint,
        payload.acknowledge_conflicts, exception_id=exception_id,
        expected_version=payload.expected_version,
    )))


class DisableRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    acknowledge_conflicts: bool = False


@router.delete("/exceptions/{exception_id}", response_model=ExceptionResponse)
def disable_exception(
    exception_id: UUID, request: Request, payload: DisableRequest,
    uow: UnitOfWork = Depends(get_uow),
):
    owner = _owner(request)
    current = _run(lambda: get_exception(uow, owner, exception_id))
    fields = {
        key: getattr(current, key) for key in ExceptionSettings.model_fields
    }
    fields["enabled"] = False
    return ExceptionResponse.from_domain(_run(lambda: save_exception(
        uow, owner, fields, payload.expected_fingerprint,
        payload.acknowledge_conflicts, exception_id=exception_id,
        expected_version=payload.expected_version,
    )))
