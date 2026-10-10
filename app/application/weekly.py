"""Weekly overview of real facts and separately recorded review intentions (TP-061)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.uow import UnitOfWork
from app.domain.capacity import WeeklyCapacityEvaluation, evaluate_week, validate_week_start
from app.domain.daily import validate_timezone
from app.domain.model import ProtectionLevel, ProjectStatus, TaskStatus
from app.domain.planning import effective_task_protection
from app.domain.weekly import WeeklyAction, WeeklyDecision, WeeklySubject

OPEN = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}


class StaleWeeklyDecision(Exception):
    """A review choice was changed since this screen was loaded."""


@dataclass(frozen=True, slots=True)
class WeeklyTask:
    task_id: UUID
    title: str
    project_id: UUID | None
    status: str
    protection: str
    due_at: datetime | None
    next_action: str | None
    last_interaction_at: datetime | None


@dataclass(frozen=True, slots=True)
class WeeklyProject:
    project_id: UUID
    title: str
    open_task_count: int
    actionable_count: int


@dataclass(frozen=True, slots=True)
class WeeklySnapshot:
    week_start: date
    timezone_name: str
    capacity_if_all_open: WeeklyCapacityEvaluation
    manual_block_count: int
    projects: tuple[WeeklyProject, ...]
    projects_without_next_action: tuple[WeeklyProject, ...]
    protected: tuple[WeeklyTask, ...]
    drifted: tuple[WeeklyTask, ...]
    no_recent_interaction: tuple[WeeklyTask, ...]
    activity_unknown: tuple[WeeklyTask, ...]
    inbox: tuple[WeeklyTask, ...]
    decisions: tuple[WeeklyDecision, ...]


def read_weekly(uow: UnitOfWork, week_start: date, timezone_name: str) -> WeeklySnapshot:
    validate_week_start(week_start)
    validate_timezone(timezone_name)
    zone = ZoneInfo(timezone_name)
    # This is a current-state review, NOT a reconstruction of a past task state.
    end = datetime.combine(week_start + timedelta(days=7), time.min, zone)
    as_of = min(end.astimezone(timezone.utc), datetime.now(timezone.utc))
    quiet_before = as_of - timedelta(days=14)

    with uow:
        tasks = uow.tasks.list_all()
        projects = sorted(
            (p for p in uow.projects.list_all() if p.status is ProjectStatus.ACTIVE),
            key=lambda p: (p.title.casefold(), str(p.id)),
        )
        open_aggregates = []
        enriched: dict[UUID, tuple[object, str | None, ProtectionLevel]] = {}
        for task in tasks:
            if task.status in OPEN:
                aggregate = uow.tasks.get_aggregate(task.id)
                if aggregate is None:
                    raise LookupError("open task aggregate not found")
                open_aggregates.append(aggregate)
                next_action = aggregate.next_action()
                enriched[task.id] = (
                    task, next_action.label if next_action else None,
                    effective_task_protection(aggregate),
                )
        capacity_blocks = uow.availability.list_week(week_start)
        capacity = evaluate_week(week_start, capacity_blocks, open_aggregates)
        interactions = uow.history.latest_task_interactions(as_of)
        def make_item(task, next_action, protection):
            return WeeklyTask(
                task_id=task.id, title=task.title, project_id=task.project_id,
                status=task.status.value, protection=protection.value,
                due_at=task.due_at, next_action=next_action,
                last_interaction_at=interactions.get(task.id),
            )

        open_items = [make_item(*enriched[t.id]) for t in tasks if t.id in enriched]
        open_items.sort(key=lambda t: (t.title.casefold(), str(t.task_id)))
        inbox = [
            WeeklyTask(t.id, t.title, t.project_id, t.status.value,
                       t.protection.value, t.due_at, None, interactions.get(t.id))
            for t in tasks if t.status is TaskStatus.INBOX
        ]
        inbox.sort(key=lambda t: (t.title.casefold(), str(t.task_id)))
        project_summaries = tuple(
            WeeklyProject(
                project_id=p.id, title=p.title,
                open_task_count=sum(t.project_id == p.id for t in open_items),
                actionable_count=sum(t.project_id == p.id and t.next_action is not None
                                     for t in open_items),
            ) for p in projects
        )
        return WeeklySnapshot(
            week_start=week_start, timezone_name=timezone_name,
            capacity_if_all_open=capacity, manual_block_count=len(capacity_blocks),
            projects=project_summaries,
            projects_without_next_action=tuple(p for p in project_summaries if not p.actionable_count),
            protected=tuple(t for t in open_items if t.protection == ProtectionLevel.PROTECTED.value),
            drifted=tuple(t for t in open_items if
                          t.due_at and t.due_at.astimezone(zone).date() < week_start),
            no_recent_interaction=tuple(t for t in (*open_items, *inbox)
                                        if t.last_interaction_at is not None
                                        and t.last_interaction_at < quiet_before),
            activity_unknown=tuple(t for t in (*open_items, *inbox)
                                   if t.last_interaction_at is None),
            inbox=tuple(inbox),
            decisions=tuple(uow.weekly_reviews.list_week(week_start, timezone_name)),
        )


def decide_weekly(
    uow: UnitOfWork, week_start: date, timezone_name: str,
    subject_kind: WeeklySubject, subject_id: UUID, action: WeeklyAction,
    review_on: date | None, expected_revision: int,
) -> WeeklyDecision:
    validate_week_start(week_start)
    validate_timezone(timezone_name)
    if expected_revision < 0:
        raise ValueError("expected_revision cannot be negative")
    with uow:
        previous = uow.weekly_reviews.get(week_start, timezone_name, subject_kind, subject_id)
        if (previous.revision if previous else 0) != expected_revision:
            raise StaleWeeklyDecision("weekly choice changed; reload before confirming")
        if subject_kind is WeeklySubject.TASK:
            task = uow.tasks.get(subject_id)
            if task is None:
                raise LookupError("task not found")
            if task.status not in OPEN | {TaskStatus.INBOX}:
                raise ValueError("weekly review only accepts open tasks or Inbox entries")
        elif subject_kind is WeeklySubject.PROJECT:
            project = uow.projects.get(subject_id)
            if project is None:
                raise LookupError("project not found")
            if project.status is not ProjectStatus.ACTIVE:
                raise ValueError("weekly review only accepts active projects")
        else:
            raise ValueError("invalid weekly subject")
        decision = WeeklyDecision(
            week_start, timezone_name, subject_kind, subject_id,
            action, review_on, datetime.now(timezone.utc), expected_revision + 1,
        )
        uow.weekly_reviews.save(decision)
        uow.commit()
        return decision
