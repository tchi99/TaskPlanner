"""Behavior observations are read only; confirmations use existing task/review commands."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.application.behavior import read_behavior
from app.application.uow import UnitOfWork
from app.infrastructure.uow import get_uow

router = APIRouter(prefix="/api/behavior", tags=["behavior"])


class TrendResponse(BaseModel):
    code: str
    scope: Literal["ALL", "WORK_TYPE"]
    work_type_id: UUID | None
    sample_size: int
    distinct_tasks: int
    minimum_samples: int
    uncertainty: Literal["LIMITED"]
    description: str
    data_quality: Literal["UNVERIFIED"]


class InterventionResponse(BaseModel):
    task_id: UUID
    task_title: str
    code: str
    observation: str
    suggestion: str
    data_quality: Literal["UNVERIFIED", "UNKNOWN"]
    requires_confirmation: Literal[True]


class BehaviorResponse(BaseModel):
    as_of: datetime
    minimum_samples: int
    data_quality: Literal["UNVERIFIED"]
    trends: list[TrendResponse]
    interventions: list[InterventionResponse]
    limitations: list[str]
    changes_applied: Literal[False]


@router.get("", response_model=BehaviorResponse)
def current_behavior(uow: UnitOfWork = Depends(get_uow)) -> BehaviorResponse:
    return BehaviorResponse(**read_behavior(uow))
