from datetime import datetime, timezone

from app.application.tasks import CaptureTaskCommand, capture_task, list_inbox
from app.domain import Task, TaskStatus


class MemoryTaskRepository:
    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def add(self, task: Task) -> Task:
        self.tasks.append(task)
        return task

    def list_inbox(self) -> list[Task]:
        return sorted(
            (task for task in self.tasks if task.status is TaskStatus.INBOX),
            key=lambda task: task.created_at,
            reverse=True,
        )


def test_capture_requires_only_a_title() -> None:
    repository = MemoryTaskRepository()

    task = capture_task(repository, CaptureTaskCommand(title="Call plumber"))

    assert task.title == "Call plumber"
    assert task.status is TaskStatus.INBOX
    assert task.notes is None
    assert task.due_at is None
    assert task.estimated_minutes is None
    assert list_inbox(repository) == [task]


def test_capture_keeps_optional_details() -> None:
    repository = MemoryTaskRepository()
    due_at = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)

    task = capture_task(
        repository,
        CaptureTaskCommand(
            title="Prepare estimate",
            notes="Check old quote first",
            due_at=due_at,
            estimated_minutes=45,
        ),
    )

    assert task.notes == "Check old quote first"
    assert task.due_at == due_at
    assert task.estimated_minutes == 45
