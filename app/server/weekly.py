"""TP-061: weekly facts and confirmed review choices, without auto execution."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.application.uow import UnitOfWork
from app.application.weekly import (
    StaleWeeklyDecision, WeeklySnapshot, WeeklyTask, WeeklyProject,
    decide_weekly, read_weekly,
)
from app.domain.weekly import WeeklyAction, WeeklyDecision, WeeklySubject
from app.infrastructure.uow import get_uow
from app.server.capacity import EvaluationResponse
from app.server.errors import invoke

router = APIRouter(prefix="/api/review/weekly", tags=["review"])


class WeeklyTaskResponse(BaseModel):
    task_id: UUID
    title: str
    project_id: UUID | None
    status: str
    protection: str
    due_at: datetime | None
    next_action: str | None
    last_interaction_at: datetime | None

    @classmethod
    def from_domain(cls, item: WeeklyTask) -> "WeeklyTaskResponse":
        return cls(**{name: getattr(item, name) for name in cls.model_fields})


class WeeklyProjectResponse(BaseModel):
    project_id: UUID
    title: str
    open_task_count: int
    actionable_count: int


class WeeklyDecisionResponse(BaseModel):
    week_start: date
    timezone_name: str
    subject_kind: WeeklySubject
    subject_id: UUID
    action: WeeklyAction
    review_on: date | None
    decided_at: datetime
    revision: int

    @classmethod
    def from_domain(cls, value: WeeklyDecision) -> "WeeklyDecisionResponse":
        return cls(**{name: getattr(value, name) for name in cls.model_fields})


class WeeklyResponse(BaseModel):
    week_start: date
    timezone_name: str
    capacity_if_all_open: EvaluationResponse
    manual_block_count: int
    projects: list[WeeklyProjectResponse]
    projects_without_next_action: list[WeeklyProjectResponse]
    protected: list[WeeklyTaskResponse]
    drifted: list[WeeklyTaskResponse]
    no_recent_interaction: list[WeeklyTaskResponse]
    activity_unknown: list[WeeklyTaskResponse]
    inbox: list[WeeklyTaskResponse]
    decisions: list[WeeklyDecisionResponse]
    calendar_written: bool = False
    tasks_modified: bool = False
    is_hypothetical: bool = True

    @classmethod
    def from_domain(cls, value: WeeklySnapshot) -> "WeeklyResponse":
        def project(p: WeeklyProject):
            return WeeklyProjectResponse(
                project_id=p.project_id, title=p.title,
                open_task_count=p.open_task_count, actionable_count=p.actionable_count,
            )
        def task(t: WeeklyTask):
            return WeeklyTaskResponse.from_domain(t)
        return cls(
            week_start=value.week_start, timezone_name=value.timezone_name,
            capacity_if_all_open=EvaluationResponse.from_domain(value.capacity_if_all_open),
            manual_block_count=value.manual_block_count,
            projects=[project(p) for p in value.projects],
            projects_without_next_action=[project(p) for p in value.projects_without_next_action],
            protected=[task(t) for t in value.protected],
            drifted=[task(t) for t in value.drifted],
            no_recent_interaction=[task(t) for t in value.no_recent_interaction],
            activity_unknown=[task(t) for t in value.activity_unknown],
            inbox=[task(t) for t in value.inbox],
            decisions=[WeeklyDecisionResponse.from_domain(d) for d in value.decisions],
        )


class WeeklyDecisionRequest(BaseModel):
    week_start: date
    timezone_name: str = "UTC"
    subject_kind: WeeklySubject
    subject_id: UUID
    action: WeeklyAction
    review_on: date | None = None
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]


def _run(action):
    try:
        return invoke(action)
    except StaleWeeklyDecision as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=WeeklyResponse)
def weekly(week_start: date, timezone_name: str = "UTC",
           uow: UnitOfWork = Depends(get_uow)) -> WeeklyResponse:
    return WeeklyResponse.from_domain(_run(lambda: read_weekly(
        uow, week_start, timezone_name,
    )))


@router.post("/decide", response_model=WeeklyDecisionResponse)
def decide(payload: WeeklyDecisionRequest,
           uow: UnitOfWork = Depends(get_uow)) -> WeeklyDecisionResponse:
    return WeeklyDecisionResponse.from_domain(_run(lambda: decide_weekly(
        uow, payload.week_start, payload.timezone_name, payload.subject_kind,
        payload.subject_id, payload.action, payload.review_on,
        payload.expected_revision,
    )))
