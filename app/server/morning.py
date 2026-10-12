"""Morning review read model. GET cannot accept/apply a plan."""
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.application.morning import morning_brief
from app.application.uow import UnitOfWork
from app.domain.morning import MorningBrief, MorningItem
from app.infrastructure.uow import get_uow
from app.server.capacity import EvaluationResponse
from app.server.errors import invoke
from app.server.recurring_availability import _owner

router = APIRouter(prefix="/api/review", tags=["review"])


class MorningItemResponse(BaseModel):
    task_id: UUID
    title: str
    protection: str
    due_at: datetime | None
    due_status: str
    next_action: str | None

    @classmethod
    def from_domain(cls, item: MorningItem) -> "MorningItemResponse":
        return cls(
            task_id=item.task_id, title=item.title,
            protection=item.protection.value, due_at=item.due_at,
            due_status=item.due_status.value, next_action=item.next_action,
        )


class DecisionResponse(BaseModel):
    code: str
    message: str


class MorningResponse(BaseModel):
    day: date
    timezone_name: str
    week_start: date
    today_available_minutes: int
    manual_block_count: int
    open_task_count: int
    inbox_count: int
    weekly_if_all_open: EvaluationResponse
    must_review: list[MorningItemResponse]
    may_slip: list[MorningItemResponse]
    decisions: list[DecisionResponse]
    is_hypothetical: bool = True
    has_daily_assignments: bool = False

    @classmethod
    def from_domain(cls, value: MorningBrief) -> "MorningResponse":
        return cls(
            day=value.day, timezone_name=value.timezone_name,
            week_start=value.week_start,
            today_available_minutes=value.today_available_minutes,
            manual_block_count=value.manual_block_count,
            open_task_count=value.open_task_count, inbox_count=value.inbox_count,
            weekly_if_all_open=EvaluationResponse.from_domain(value.weekly_if_all_open),
            must_review=[MorningItemResponse.from_domain(v) for v in value.must_review],
            may_slip=[MorningItemResponse.from_domain(v) for v in value.may_slip],
            decisions=[DecisionResponse(code=v.code, message=v.message) for v in value.decisions],
        )


@router.get("/morning", response_model=MorningResponse)
def morning(day: date, request: Request, timezone_name: str = "UTC",
            uow: UnitOfWork = Depends(get_uow)) -> MorningResponse:
    return MorningResponse.from_domain(invoke(
        lambda: morning_brief(uow, day, timezone_name, _owner(request))
    ))
