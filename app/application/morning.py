"""Read-only morning projection; no stored day selection or plan mutation."""
from __future__ import annotations

from datetime import date

from app.application.uow import UnitOfWork
from app.application.planning_availability import effective_week
from app.domain.model import TaskStatus
from app.domain.morning import MorningBrief, build_morning_brief


def morning_brief(uow: UnitOfWork, day: date, timezone_name: str,
                  owner_id: str = "urn:taskplanner:local") -> MorningBrief:
    monday = day.fromordinal(day.toordinal() - day.weekday())
    with uow:
        all_tasks = uow.tasks.list_all()
        aggregates = []
        for task in all_tasks:
            if task.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
                aggregate = uow.tasks.get_aggregate(task.id)
                if aggregate is None:
                    raise LookupError(f"task {task.id} not found")
                aggregates.append(aggregate)
        return build_morning_brief(
            day, timezone_name,
            effective_week(uow, owner_id, monday, timezone_name).blocks,
            aggregates, sum(task.status is TaskStatus.INBOX for task in all_tasks),
            manual_block_count=len(uow.availability.list_week(monday)),
        )
