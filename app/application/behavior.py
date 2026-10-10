"""Read-only TP-072 use case. No external API, persistence or AI dependency."""
from datetime import datetime, timezone

from app.application.uow import UnitOfWork
from app.application.work_sessions import descriptive_statistics
from app.domain.behavior import project_behavior
from app.domain.model import TaskStatus


def read_behavior(uow: UnitOfWork, *, now: datetime | None = None) -> dict:
    at = now or datetime.now(timezone.utc)
    with uow:
        tasks = tuple(uow.tasks.list_all())
        events = tuple(uow.history_read.list_all(before=at))
        sessions = tuple(uow.work_sessions.list_all())
        decomposed_ids = {
            task.id for task in tasks
            if task.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
            and task.estimated_minutes is not None and task.estimated_minutes >= 90
            and (aggregate := uow.tasks.get_aggregate(task.id)) is not None
            and bool(aggregate.segments)
        }
    return project_behavior(
        as_of=at, tasks=tasks, events=events, sessions=sessions,
        decomposed_ids=decomposed_ids,
        calibration=descriptive_statistics(uow),
    )
