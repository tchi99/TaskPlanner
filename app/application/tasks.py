from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from app.domain import Task, TaskStatus


class TaskRepository(Protocol):
    def add(self, task: Task) -> Task: ...

    def list_inbox(self) -> Sequence[Task]: ...


@dataclass(frozen=True, slots=True)
class CaptureTaskCommand:
    title: str
    notes: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = None


def capture_task(repository: TaskRepository, command: CaptureTaskCommand) -> Task:
    task = Task(
        title=command.title,
        notes=command.notes,
        due_at=command.due_at,
        estimated_minutes=command.estimated_minutes,
        status=TaskStatus.INBOX,
    )
    return repository.add(task)


def list_inbox(repository: TaskRepository) -> Sequence[Task]:
    return repository.list_inbox()
