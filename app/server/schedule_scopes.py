"""Backend APIs for ScheduleScope parent identities and dated leaf affiliations."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.application.schedule_scopes import (
    AffiliationDraft, list_scopes, create_scope, update_scope,
    preview_affiliation, confirm_affiliation,
)
from app.domain.recurring_availability import RuleConflict
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/schedule-scopes", tags=["schedule-scopes"])


def _run(action):
    try:
        return invoke(action)
    except RuleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class CreateScope(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateScope(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    state: str = "ACTIVE"
    expected_version: int = Field(ge=1)


class AffiliationInput(BaseModel):
    work_type_id: UUID
    scope_id: UUID
    effective_from: date
    timezone_name: str = Field(min_length=1, max_length=100)
    expected_affiliation_version: int = Field(ge=0)
    expected_scope_version: int = Field(ge=1)
    remap_rule_ids: list[UUID] = Field(default_factory=list)

    def to_domain(self):
        return AffiliationDraft(
            self.work_type_id, self.scope_id, self.effective_from,
            self.timezone_name, self.expected_affiliation_version,
            self.expected_scope_version, tuple(self.remap_rule_ids),
        )


class ConfirmAffiliation(AffiliationInput):
    command_id: UUID
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: bool
    acknowledge_bookings: bool = False


@router.get("")
def scopes(request: Request, uow=Depends(get_uow)):
    return _run(lambda: list_scopes(uow, _owner(request)))


@router.post("", status_code=201)
def add(request: Request, body: CreateScope, uow=Depends(get_uow)):
    return _run(lambda: create_scope(uow, _owner(request), body.name))


@router.patch("/{scope_id}")
def change(scope_id: UUID, request: Request, body: UpdateScope, uow=Depends(get_uow)):
    return _run(lambda: update_scope(uow, _owner(request), scope_id,
                                     body.expected_version, body.name, body.state))


@router.post("/affiliations/preview")
def preview(request: Request, body: AffiliationInput, uow=Depends(get_uow)):
    return _run(lambda: preview_affiliation(uow, _owner(request), body.to_domain()))


@router.post("/affiliations/confirm")
def confirm(request: Request, body: ConfirmAffiliation, uow=Depends(get_uow)):
    return _run(lambda: confirm_affiliation(
        uow, _owner(request), body.to_domain(), fingerprint=body.fingerprint,
        command_id=body.command_id, confirmed=body.confirmed,
        acknowledge_bookings=body.acknowledge_bookings,
    ))
