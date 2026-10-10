"""TP-060 daily review: read, explicitly choose/revise, explicitly close."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.application.daily import (
    DailySnapshot, DailyTaskItem, StaleDailyReview,
    close_daily, read_daily, select_daily,
)
from app.application.uow import UnitOfWork
from app.domain.daily import DailyFollowup
from app.infrastructure.uow import get_uow
from app.server.errors import invoke

router = APIRouter(prefix="/api/review/daily", tags=["review"])


class DailyItemResponse(BaseModel):
    task_id: UUID
    title: str
    status: str
    protection: str
    due_at: datetime | None
    next_action: str | None
    reason: str | None
    review_on: date | None

    @classmethod
    def from_domain(cls, value: DailyTaskItem) -> "DailyItemResponse":
        return cls(
            task_id=value.task_id, title=value.title, status=value.status.value,
            protection=value.protection.value, due_at=value.due_at,
            next_action=value.next_action,
            reason=value.reason.value if value.reason else None,
            review_on=value.review_on,
        )


class FollowupResponse(BaseModel):
    task_id: UUID
    review_on: date


class DailyResponse(BaseModel):
    day: date
    timezone_name: str
    state: Literal["NOT_CHOSEN", "OPEN", "CLOSED"]
    revision: int
    selected_task_ids: list[UUID]
    selected: list[DailyItemResponse]
    resurfaced: list[DailyItemResponse]
    followups: list[FollowupResponse]
    calendar_written: bool = False

    @classmethod
    def from_domain(cls, value: DailySnapshot) -> "DailyResponse":
        return cls(
            day=value.day, timezone_name=value.timezone_name,
            state=value.state, revision=value.revision,
            selected_task_ids=list(value.selected_task_ids),
            selected=[DailyItemResponse.from_domain(v) for v in value.selected],
            resurfaced=[DailyItemResponse.from_domain(v) for v in value.resurfaced],
            followups=[FollowupResponse(task_id=v.task_id, review_on=v.review_on)
                       for v in value.followups],
        )


class DailyChoiceRequest(BaseModel):
    day: date
    timezone_name: str = "UTC"
    task_ids: list[UUID]
    expected_revision: int = Field(ge=0)
    reason: Literal["MORNING", "SIGNIFICANT_EVENT"]
    confirmed: Literal[True]


class CloseDailyRequest(BaseModel):
    day: date
    timezone_name: str = "UTC"
    expected_revision: int = Field(ge=1)
    followups: list[FollowupResponse]
    confirmed: Literal[True]


def _run(action):
    try:
        return invoke(action)
    except StaleDailyReview as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=DailyResponse)
def get_daily(
    day: date, timezone_name: str = "UTC",
    uow: UnitOfWork = Depends(get_uow),
) -> DailyResponse:
    return DailyResponse.from_domain(_run(
        lambda: read_daily(uow, day, timezone_name)
    ))


@router.post("/select", response_model=DailyResponse)
def choose(
    payload: DailyChoiceRequest, uow: UnitOfWork = Depends(get_uow),
) -> DailyResponse:
    def action():
        select_daily(uow, payload.day, payload.timezone_name,
                     payload.task_ids, payload.expected_revision, payload.reason)
        return read_daily(uow, payload.day, payload.timezone_name)
    return DailyResponse.from_domain(_run(action))


@router.post("/close", response_model=DailyResponse)
def close(
    payload: CloseDailyRequest, uow: UnitOfWork = Depends(get_uow),
) -> DailyResponse:
    def action():
        close_daily(
            uow, payload.day, payload.timezone_name, payload.expected_revision,
            [DailyFollowup(item.task_id, item.review_on) for item in payload.followups],
        )
        return read_daily(uow, payload.day, payload.timezone_name)
    return DailyResponse.from_domain(_run(action))
