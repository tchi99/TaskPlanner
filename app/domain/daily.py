"""Explicit daily choices and non-judgmental resurfacing (TP-060)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DailyState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RevisitReason(StrEnum):
    UNFINISHED_DAY = "UNFINISHED_DAY"
    REVIEW_DUE = "REVIEW_DUE"


@dataclass(frozen=True, slots=True)
class DailyFollowup:
    task_id: UUID
    review_on: date


@dataclass(frozen=True, slots=True)
class DailyReview:
    day: date
    timezone_name: str
    selected_task_ids: tuple[UUID, ...]
    state: DailyState = DailyState.OPEN
    followups: tuple[DailyFollowup, ...] = ()
    revision: int = 1

    def __post_init__(self) -> None:
        validate_timezone(self.timezone_name)
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if len(set(self.selected_task_ids)) != len(self.selected_task_ids):
            raise ValueError("selected task IDs must be unique")
        if self.state is DailyState.OPEN and self.followups:
            raise ValueError("open daily review cannot have final followups")
        ids = [entry.task_id for entry in self.followups]
        if len(set(ids)) != len(ids) or not set(ids) <= set(self.selected_task_ids):
            raise ValueError("followups must reference distinct selected tasks")
        if any(entry.review_on <= self.day for entry in self.followups):
            raise ValueError("next review must be after the reviewed day")


@dataclass(frozen=True, slots=True)
class Revisit:
    task_id: UUID
    reason: RevisitReason
    review_on: date | None


def validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc


def resurfaced(
    earlier: Sequence[DailyReview], day: date,
    open_task_ids: set[UUID], selected_today: set[UUID],
) -> tuple[Revisit, ...]:
    """Latest daily outcome for each task wins; no inactivity inference."""
    pending: dict[UUID, Revisit] = {}
    for review in sorted((r for r in earlier if r.day < day),
                         key=lambda r: (r.day, r.revision)):
        followups = {item.task_id: item.review_on for item in review.followups}
        for task_id in review.selected_task_ids:
            if review.state is DailyState.OPEN:
                pending[task_id] = Revisit(task_id, RevisitReason.UNFINISHED_DAY, None)
            elif task_id in followups:
                pending[task_id] = Revisit(
                    task_id, RevisitReason.REVIEW_DUE, followups[task_id],
                )
            else:
                pending.pop(task_id, None)
    return tuple(sorted((
        item for item in pending.values()
        if item.task_id in open_task_ids and item.task_id not in selected_today
        and (item.review_on is None or item.review_on <= day)
    ), key=lambda item: (item.review_on or date.min, str(item.task_id))))
