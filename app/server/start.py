"""HTTP adapter for on-demand start assistance and explicit resume point updates."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.application.start import (
    StartAssistance, StaleResumePointError, get_start_assistance, save_resume_point,
)
from app.application.uow import UnitOfWork
from app.domain.task_rules import NextActionType
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.schemas import NextActionResponse

router = APIRouter(prefix="/api/tasks", tags=["start-assistance"])


class StarterActionResponse(BaseModel):
    text: str
    commitment_minutes: int


class StrategyResponse(BaseModel):
    code: str
    label: str


class ResumePointResponse(BaseModel):
    text: str
    action_type: NextActionType
    target_id: UUID
    updated_at: datetime


class StartAssistanceResponse(BaseModel):
    next_action: NextActionResponse | None
    starter_action: StarterActionResponse | None
    strategies: list[StrategyResponse]
    resume_point: ResumePointResponse | None
    resume_revision: int

    @classmethod
    def from_domain(cls, value: StartAssistance) -> "StartAssistanceResponse":
        action = value.next_action
        starter = value.starter_action
        marker = value.resume_point
        return cls(
            next_action=NextActionResponse(
                action_type=action.action_type.value,
                target_id=action.target_id,
                label=action.label,
            ) if action else None,
            starter_action=StarterActionResponse(
                text=starter.text, commitment_minutes=starter.commitment_minutes,
            ) if starter else None,
            strategies=[StrategyResponse(code=s.code, label=s.label) for s in value.strategies],
            resume_point=ResumePointResponse(
                text=marker.text, action_type=marker.action_type,
                target_id=marker.target_id, updated_at=marker.updated_at,
            ) if marker and marker.text is not None else None,
            resume_revision=value.resume_revision,
        )


class ResumePointRequest(BaseModel):
    text: str | None = Field(max_length=240)
    action_type: NextActionType
    target_id: UUID
    expected_revision: int = Field(ge=0)
    confirmed: bool


@router.get("/{task_id}/start-assistance", response_model=StartAssistanceResponse)
def read_assistance(
    task_id: UUID, uow: UnitOfWork = Depends(get_uow),
) -> StartAssistanceResponse:
    return StartAssistanceResponse.from_domain(invoke(
        lambda: get_start_assistance(uow, task_id)
    ))


@router.put("/{task_id}/start-assistance/resume-point", response_model=StartAssistanceResponse)
def update_resume_point(
    task_id: UUID, payload: ResumePointRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> StartAssistanceResponse:
    try:
        result = invoke(lambda: save_resume_point(
            uow, task_id, text=payload.text, action_type=payload.action_type,
            target_id=payload.target_id, expected_revision=payload.expected_revision,
            confirmed=payload.confirmed,
        ))
        return StartAssistanceResponse.from_domain(result)
    except StaleResumePointError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
