"""Read-only weekly plan proposal endpoint; never accepts a decision."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.application.planning import propose_week
from app.application.uow import UnitOfWork
from app.domain.planning import PlanOptionPreview, PlanProposalPreview
from app.infrastructure.uow import get_uow
from app.server.capacity import EvaluationResponse, SelectionRequest
from app.server.errors import invoke

router = APIRouter(prefix="/api/capacity/weeks", tags=["planning"])


class OptionResponse(BaseModel):
    id: UUID
    kind: str
    label: str
    rationale: str
    affected_item_ids: list[UUID]
    consequences: list[str]
    excluded_task_ids: list[UUID]
    capacity: EvaluationResponse | None
    requires_confirmation: bool

    @classmethod
    def from_domain(cls, preview: PlanOptionPreview) -> "OptionResponse":
        option = preview.option
        return cls(
            id=option.id, kind=preview.kind.value, label=option.label,
            rationale=option.rationale,
            affected_item_ids=list(option.affected_item_ids),
            consequences=list(option.consequences),
            excluded_task_ids=list(preview.excluded_task_ids),
            capacity=(EvaluationResponse.from_domain(preview.capacity)
                      if preview.capacity is not None else None),
            requires_confirmation=preview.requires_confirmation,
        )


class ProposalResponse(BaseModel):
    id: UUID
    week_start: date
    created_at: datetime
    candidate_task_ids: list[UUID]
    facts: list[str]
    baseline: EvaluationResponse
    options: list[OptionResponse]
    state: str = "PROPOSED"

    @classmethod
    def from_domain(cls, value: PlanProposalPreview) -> "ProposalResponse":
        return cls(
            id=value.proposal.id,
            week_start=value.week_start,
            created_at=value.proposal.created_at,
            candidate_task_ids=list(value.candidate_task_ids),
            facts=list(value.proposal.facts),
            baseline=EvaluationResponse.from_domain(value.baseline),
            options=[OptionResponse.from_domain(v) for v in value.options],
        )


@router.post("/{week_start}/proposals", response_model=ProposalResponse)
def propose(week_start: date, payload: SelectionRequest,
            uow: UnitOfWork = Depends(get_uow)) -> ProposalResponse:
    return ProposalResponse.from_domain(invoke(
        lambda: propose_week(uow, week_start, payload.task_ids)
    ))
