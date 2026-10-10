"""Daily selection, on-demand re-evaluation, and explicit end-of-day closure.

Daily choices never change task status, protection, due dates or calendar events.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence
from uuid import UUID

from app.application.uow import UnitOfWork
from app.domain.daily import (
    DailyFollowup, DailyReview, DailyState, RevisitReason, resurfaced,
    validate_timezone,
)
from app.domain.model import ProtectionLevel, TaskStatus
from app.domain.planning import effective_task_protection

OPEN_TASKS = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}


class StaleDailyReview(Exception):
    """The selected review revision is no longer current."""


@dataclass(frozen=True, slots=True)
class DailyTaskItem:
    task_id: UUID
    title: str
    status: TaskStatus
    protection: ProtectionLevel
    due_at: datetime | None
    next_action: str | None
    reason: RevisitReason | None = None
    review_on: date | None = None


@dataclass(frozen=True, slots=True)
class DailySnapshot:
    day: date
    timezone_name: str
    state: str
    revision: int
    selected_task_ids: tuple[UUID, ...]
    selected: tuple[DailyTaskItem, ...]
    resurfaced: tuple[DailyTaskItem, ...]
    followups: tuple[DailyFollowup, ...]


def read_daily(uow: UnitOfWork, day: date, timezone_name: str) -> DailySnapshot:
    validate_timezone(timezone_name)
    with uow:
        current = uow.daily_reviews.get(day, timezone_name)
        earlier = uow.daily_reviews.list_before(day, timezone_name)
        tasks = {task.id: task for task in uow.tasks.list_all()}
        chosen = set(current.selected_task_ids) if current else set()
        open_ids = {task_id for task_id, task in tasks.items()
                    if task.status in OPEN_TASKS}
        reminders = resurfaced(earlier, day, open_ids, chosen)

        def item(task_id: UUID, reason=None, review_on=None) -> DailyTaskItem:
            aggregate = uow.tasks.get_aggregate(task_id)
            if aggregate is None:
                raise LookupError(f"task {task_id} not found")
            action = aggregate.next_action()
            return DailyTaskItem(
                task_id=task_id, title=aggregate.task.title,
                status=aggregate.task.status,
                protection=effective_task_protection(aggregate),
                due_at=aggregate.task.due_at,
                next_action=action.label if action else None,
                reason=reason, review_on=review_on,
            )

        return DailySnapshot(
            day=day, timezone_name=timezone_name,
            state=current.state.value if current else "NOT_CHOSEN",
            revision=current.revision if current else 0,
            selected_task_ids=current.selected_task_ids if current else (),
            selected=tuple(item(task_id) for task_id in
                           (current.selected_task_ids if current else ())),
            resurfaced=tuple(item(r.task_id, r.reason, r.review_on)
                             for r in reminders),
            followups=current.followups if current else (),
        )


def select_daily(
    uow: UnitOfWork, day: date, timezone_name: str,
    task_ids: Sequence[UUID], expected_revision: int, reason: str,
) -> DailyReview:
    validate_timezone(timezone_name)
    if expected_revision < 0:
        raise ValueError("expected_revision cannot be negative")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("selected task IDs must be unique")
    if reason not in {"MORNING", "SIGNIFICANT_EVENT"}:
        raise ValueError("invalid selection reason")
    with uow:
        previous = uow.daily_reviews.get(day, timezone_name)
        if (previous.revision if previous else 0) != expected_revision:
            raise StaleDailyReview("daily review changed; reload before confirming")
        if previous and previous.state is DailyState.CLOSED:
            raise ValueError("closed daily review cannot be changed")
        if (previous is None and reason != "MORNING") or (
            previous is not None and reason != "SIGNIFICANT_EVENT"
        ):
            raise ValueError("morning choice starts a day; later edits require a significant event")
        for task_id in task_ids:
            aggregate = uow.tasks.get_aggregate(task_id)
            if aggregate is None:
                raise LookupError(f"task {task_id} not found")
            if aggregate.task.status not in OPEN_TASKS:
                raise ValueError("daily selection requires open clarified tasks")
        review = DailyReview(
            day=day, timezone_name=timezone_name,
            selected_task_ids=tuple(task_ids), revision=expected_revision + 1,
        )
        uow.daily_reviews.save(review)
        uow.commit()
        return review


def close_daily(
    uow: UnitOfWork, day: date, timezone_name: str,
    expected_revision: int, followups: Sequence[DailyFollowup],
) -> DailyReview:
    validate_timezone(timezone_name)
    with uow:
        previous = uow.daily_reviews.get(day, timezone_name)
        if previous is None:
            raise LookupError("daily review not chosen")
        if previous.revision != expected_revision:
            raise StaleDailyReview("daily review changed; reload before confirming")
        if previous.state is DailyState.CLOSED:
            raise ValueError("daily review already closed")
        open_selected: set[UUID] = set()
        for task_id in previous.selected_task_ids:
            task = uow.tasks.get(task_id)
            if task is None:
                raise LookupError(f"task {task_id} not found")
            if task.status in OPEN_TASKS:
                open_selected.add(task_id)
        if len({f.task_id for f in followups}) != len(followups) or {
            f.task_id for f in followups
        } != open_selected:
            raise ValueError("each still-open selected task requires one explicit next review date")
        closed = DailyReview(
            day=day, timezone_name=timezone_name,
            selected_task_ids=previous.selected_task_ids,
            state=DailyState.CLOSED, followups=tuple(followups),
            revision=expected_revision + 1,
        )
        uow.daily_reviews.save(closed)
        uow.commit()
        return closed
