"""Explicit weekly review decisions, separate from task/calendar mutations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.domain.capacity import validate_week_start
from app.domain.daily import validate_timezone


class WeeklySubject(StrEnum):
    TASK = "TASK"
    PROJECT = "PROJECT"


class WeeklyAction(StrEnum):
    RECIRCULATE = "RECIRCULATE"
    POSTPONE = "POSTPONE"
    REVIEW_LATER = "REVIEW_LATER"
    DELEGATE = "DELEGATE"
    ABANDON = "ABANDON"


@dataclass(frozen=True, slots=True)
class WeeklyDecision:
    week_start: date
    timezone_name: str
    subject_kind: WeeklySubject
    subject_id: UUID
    action: WeeklyAction
    review_on: date | None
    decided_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        validate_week_start(self.week_start)
        validate_timezone(self.timezone_name)
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        if self.action in {WeeklyAction.POSTPONE, WeeklyAction.REVIEW_LATER} and self.review_on is None:
            raise ValueError("postpone/review later requires a next review date")
        if self.review_on is not None and self.review_on < self.week_start + timedelta(days=7):
            raise ValueError("next review must be after the reviewed week")
