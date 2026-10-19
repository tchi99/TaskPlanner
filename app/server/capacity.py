"""Read-only physical-capacity evaluation; no legacy manual-block writes."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.application.capacity import evaluate_selection
from app.application.uow import UnitOfWork
from app.domain.capacity import WeeklyCapacityEvaluation
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner


router = APIRouter(prefix="/api/capacity/weeks", tags=["capacity"])


class CapacityByTypeResponse(BaseModel):
    work_type_id: UUID | None
    scope_id: UUID | None = None
    alternative_potential: bool = False
    available_minutes: int
    known_demand_minutes: int
    unestimated_units: int
    remaining_minutes: int
    status: str


class EvaluationResponse(BaseModel):
    projection: str = "DECLARED_NOT_CALENDAR_VERIFIED"
    calendar_checked: bool = False
    week_start: date
    available_minutes: int
    known_demand_minutes: int
    unestimated_units: int
    remaining_minutes: int
    status: str
    by_work_type: list[CapacityByTypeResponse]

    @classmethod
    def from_domain(cls, value: WeeklyCapacityEvaluation) -> "EvaluationResponse":
        return cls(
            week_start=value.week_start,
            available_minutes=value.available_minutes,
            known_demand_minutes=value.known_demand_minutes,
            unestimated_units=value.unestimated_units,
            remaining_minutes=value.remaining_minutes,
            status=value.status.value,
            by_work_type=[
                CapacityByTypeResponse(
                    work_type_id=b.work_type_id, scope_id=b.scope_id,
                    alternative_potential=b.alternative_potential,
                    available_minutes=b.available_minutes,
                    known_demand_minutes=b.known_demand_minutes,
                    unestimated_units=b.unestimated_units,
                    remaining_minutes=b.remaining_minutes,
                    status=b.status.value,
                )
                for b in value.by_work_type
            ],
        )


class SelectionRequest(BaseModel):
    task_ids: list[UUID]
    timezone_name: str = "UTC"


@router.post("/{week_start}/evaluate", response_model=EvaluationResponse)
def evaluate(
    week_start: date,
    payload: SelectionRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> EvaluationResponse:
    return EvaluationResponse.from_domain(invoke(
        lambda: evaluate_selection(uow, week_start, payload.task_ids,
                                   payload.timezone_name, _owner(request))
    ))
