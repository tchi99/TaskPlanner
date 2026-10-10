"""HTTP adapters for explicit WorkSession actions; no browser-side timer authority."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.application.uow import UnitOfWork
from app.application.work_sessions import (
    change_session, descriptive_statistics, read_task_observation, start_session,
)
from app.domain.work_sessions import SessionConflict, WorkSession
from app.infrastructure.uow import get_uow
from app.server.errors import invoke

task_router = APIRouter(prefix="/api/tasks", tags=["work-sessions"])
session_router = APIRouter(prefix="/api/work-sessions", tags=["work-sessions"])


class WorkSessionResponse(BaseModel):
    id: UUID
    task_id: UUID
    segment_id: UUID | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    revision: int
    recorded_active_seconds: int
    provisional_active_seconds: int
    interruptions: int
    work_type_id: UUID | None
    estimated_minutes: int | None
    planned_minutes: int | None
    guardrail: str | None

    @classmethod
    def from_domain(cls, value: WorkSession) -> "WorkSessionResponse":
        now = datetime.now(timezone.utc)
        provisional = (value.observed_seconds(now) - value.active_seconds
                       if value.active_since and now >= value.active_since else 0)
        return cls(
            id=value.id, task_id=value.task_id, segment_id=value.segment_id,
            started_at=value.started_at, finished_at=value.finished_at,
            status=value.status.value, revision=value.revision,
            recorded_active_seconds=value.active_seconds,
            provisional_active_seconds=provisional,
            interruptions=value.interruptions, work_type_id=value.work_type_id,
            estimated_minutes=value.estimated_minutes, planned_minutes=value.planned_minutes,
            guardrail=value.guardrail(now) if now >= value.started_at else None,
        )


class StartWorkSessionRequest(BaseModel):
    segment_id: UUID | None = None
    planned_minutes: int | None = Field(default=None, gt=0, le=1440)


class SessionTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason_code: Literal["INTERRUPTION", "BLOCKED", "USER_CHOICE", "OTHER"] | None = None


class TaskObservationResponse(BaseModel):
    sessions: list[WorkSessionResponse]
    estimate_minutes: int | None
    estimate_incomplete: bool
    recorded_active_seconds: int
    provisional_active_seconds: int
    observed_minutes: float
    difference_minutes: float | None
    has_open_sessions: bool
    coverage: str
    disclaimer: str


class WorkTypeStatisticsResponse(BaseModel):
    work_type_id: UUID | None
    work_type_name: str
    context: Literal["TASK", "SEGMENT"]
    finished_sessions: int
    median_session_minutes: float | None
    interruption_frequency: float | None
    completed_unit_samples: int
    minimum_samples: int
    calibration_ready: bool
    median_estimated_minutes: float | None
    median_observed_minutes: float | None
    deviations_minutes: list[float]
    coverage: str


def _run(action):
    try:
        return invoke(action)
    except SessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@task_router.get("/{task_id}/work-sessions", response_model=TaskObservationResponse)
def list_task_sessions(
    task_id: UUID, uow: UnitOfWork = Depends(get_uow),
) -> TaskObservationResponse:
    result = _run(lambda: read_task_observation(uow, task_id))
    return TaskObservationResponse(
        **{key: value for key, value in result.items() if key != "sessions"},
        sessions=[WorkSessionResponse.from_domain(session) for session in result["sessions"]],
    )


@task_router.post("/{task_id}/work-sessions", response_model=WorkSessionResponse, status_code=201)
def create_work_session(
    task_id: UUID, payload: StartWorkSessionRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> WorkSessionResponse:
    value = _run(lambda: start_session(
        uow, task_id, segment_id=payload.segment_id, planned_minutes=payload.planned_minutes,
    ))
    return WorkSessionResponse.from_domain(value)


@session_router.get("/stats", response_model=list[WorkTypeStatisticsResponse])
def statistics(uow: UnitOfWork = Depends(get_uow)) -> list[WorkTypeStatisticsResponse]:
    return [WorkTypeStatisticsResponse(**entry)
            for entry in _run(lambda: descriptive_statistics(uow))]


@session_router.post("/{session_id}/{action}", response_model=WorkSessionResponse)
def transition_work_session(
    session_id: UUID, action: Literal["pause", "resume", "finish"],
    payload: SessionTransitionRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> WorkSessionResponse:
    value = _run(lambda: change_session(
        uow, session_id, action=action, expected_revision=payload.expected_revision,
        reason_code=payload.reason_code,
    ))
    return WorkSessionResponse.from_domain(value)
