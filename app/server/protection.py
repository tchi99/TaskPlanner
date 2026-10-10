"""Simulation-only TP-021 endpoint."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from app.application.protection import preview_displacement
from app.domain.model import ProtectionLevel
from app.infrastructure.uow import get_uow
from app.application.uow import UnitOfWork
from app.server.errors import invoke

router = APIRouter(prefix="/api/tasks", tags=["protection"])


class DisplacementRequest(BaseModel):
    original_at: datetime
    proposed_at: datetime
    segment_id: UUID | None = None

    @field_validator("original_at", "proposed_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("a timezone is required")
        return value


class DisplacementResponse(BaseModel):
    task_id: UUID
    segment_id: UUID | None
    protection: ProtectionLevel
    original_at: datetime
    proposed_at: datetime
    delay_minutes: int
    reason_code: str
    rationale: str
    consequences: tuple[str, ...]
    deadline_crossed: bool
    starts_after_deadline: bool
    confirmation_required: bool
    estimate_unknown: bool


@router.post("/{task_id}/displacement-preview", response_model=DisplacementResponse)
def preview(
    task_id: UUID, payload: DisplacementRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> DisplacementResponse:
    assessment = invoke(lambda: preview_displacement(
        uow, task_id, payload.original_at, payload.proposed_at, payload.segment_id
    ))
    return DisplacementResponse.model_validate(assessment, from_attributes=True)
