from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.application.history import HistorySource, build_history_events
from app.application.uow import UnitOfWork
from app.domain import (
    DomainEntityType,
    DomainFact,
    DomainFactType,
    FactRole,
    Task,
    TaskCaptured,
    TaskStatus,
)


@dataclass(frozen=True, slots=True)
class CaptureTaskCommand:
    title: str
    notes: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = None


def capture_task(uow: UnitOfWork, command: CaptureTaskCommand) -> Task:
    task = Task(
        title=command.title,
        notes=command.notes,
        due_at=command.due_at,
        estimated_minutes=command.estimated_minutes,
        status=TaskStatus.INBOX,
    )
    captured = DomainFact(
        event_type=DomainFactType.TASK_CAPTURED,
        entity_type=DomainEntityType.TASK,
        entity_id=task.id,
        task_id=task.id,
        role=FactRole.DIRECT,
        payload=TaskCaptured(
            status=task.status,
            estimated_minutes=task.estimated_minutes,
            work_type_id=task.work_type_id,
        ),
    )
    events = build_history_events(
        (captured,),
        direct_source=HistorySource.USER,
        occurred_at=task.created_at,
    )

    with uow:
        uow.tasks.add(task)
        uow.history.append_many(events)
        uow.commit()
    return task


def list_inbox(uow: UnitOfWork) -> Sequence[Task]:
    with uow:
        return tuple(uow.tasks.list_inbox())
