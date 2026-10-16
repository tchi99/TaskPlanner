"""HTTP boundary for manual availability and read-only capacity checks."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, field_validator

from app.application.capacity import (
    add_block, delete_block, evaluate_selection, list_blocks,
)
from app.application.uow import UnitOfWork
from app.domain.capacity import (
    AvailabilityBlock, WeeklyCapacityEvaluation, evaluate_week,
)
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner


router = APIRouter(prefix="/api/capacity/weeks", tags=["capacity"])


class AvailabilityBlockRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("availability timestamps must include a timezone")
        return value


class AvailabilityBlockResponse(BaseModel):
    id: UUID
    week_start: date
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None
    minutes: int

    @classmethod
    def from_domain(cls, block: AvailabilityBlock) -> "AvailabilityBlockResponse":
        return cls(
            id=block.id, week_start=block.week_start,
            starts_at=block.starts_at, ends_at=block.ends_at,
            work_type_id=block.work_type_id, minutes=block.minutes,
        )


class CapacityByTypeResponse(BaseModel):
    work_type_id: UUID | None
    scope_id: UUID | None = None
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
                    available_minutes=b.available_minutes,
                    known_demand_minutes=b.known_demand_minutes,
                    unestimated_units=b.unestimated_units,
                    remaining_minutes=b.remaining_minutes,
                    status=b.status.value,
                )
                for b in value.by_work_type
            ],
        )


class WeekResponse(BaseModel):
    week_start: date
    blocks: list[AvailabilityBlockResponse]
    capacity: EvaluationResponse


class SelectionRequest(BaseModel):
    task_ids: list[UUID]
    timezone_name: str = "UTC"


@router.get("/{week_start}", response_model=WeekResponse)
def get_week(week_start: date, uow: UnitOfWork = Depends(get_uow)) -> WeekResponse:
    blocks = invoke(lambda: list_blocks(uow, week_start))
    return WeekResponse(
        week_start=week_start,
        blocks=[AvailabilityBlockResponse.from_domain(block) for block in blocks],
        capacity=EvaluationResponse.from_domain(evaluate_week(week_start, blocks, [])),
    )


@router.post(
    "/{week_start}/blocks",
    response_model=AvailabilityBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_block(
    week_start: date,
    payload: AvailabilityBlockRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> AvailabilityBlockResponse:
    return AvailabilityBlockResponse.from_domain(invoke(lambda: add_block(
        uow, week_start, payload.starts_at, payload.ends_at, payload.work_type_id,
    )))


@router.delete(
    "/{week_start}/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_block(
    week_start: date,
    block_id: UUID,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    invoke(lambda: delete_block(uow, week_start, block_id))


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
