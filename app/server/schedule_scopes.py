"""Real scheduling parent API. No historical WorkType reassignment routes."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from app.application.schedule_scopes import list_scopes, create_scope, update_scope
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


@router.get("")
def scopes(request: Request, uow=Depends(get_uow)):
    return _run(lambda: list_scopes(uow, _owner(request)))


@router.post("", status_code=status.HTTP_201_CREATED)
def add(request: Request, body: CreateScope, uow=Depends(get_uow)):
    return _run(lambda: create_scope(uow, _owner(request), body.name))


@router.patch("/{scope_id}")
def change(scope_id: UUID, request: Request, body: UpdateScope, uow=Depends(get_uow)):
    return _run(lambda: update_scope(uow, _owner(request), scope_id,
                                     body.expected_version, body.name, body.state))
