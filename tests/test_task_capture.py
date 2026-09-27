from datetime import datetime, timezone

from app.application.history import HistoryEvent
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


class MemoryHistoryRepository:
    def __init__(self) -> None:
        self.events: list[HistoryEvent] = []

    def append(self, event: HistoryEvent) -> None:
        self.events.append(event)

    def append_many(self, events) -> None:
        self.events.extend(events)


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.tasks = MemoryTaskRepository()
        self.history = MemoryHistoryRepository()
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_capture_requires_only_a_title_and_records_history() -> None:
    uow = MemoryUnitOfWork()

    task = capture_task(uow, CaptureTaskCommand(title="Call plumber"))

    assert task.title == "Call plumber"
    assert task.status is TaskStatus.INBOX
    assert task.notes is None
    assert task.due_at is None
    assert task.estimated_minutes is None
    assert list_inbox(uow) == (task,)
    assert uow.commits == 1
    assert len(uow.history.events) == 1
    assert uow.history.events[0].event_type == "TASK_CAPTURED"


def test_capture_keeps_optional_details_without_copying_text_to_history() -> None:
    uow = MemoryUnitOfWork()
    due_at = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)

    task = capture_task(
        uow,
        CaptureTaskCommand(
            title="Prepare estimate",
            notes="Check old quote first",
            due_at=due_at,
            estimated_minutes=45,
        ),
    )

    event = uow.history.events[0]
    assert task.notes == "Check old quote first"
    assert task.due_at == due_at
    assert task.estimated_minutes == 45
    assert event.payload == {
        "status": "INBOX",
        "estimated_minutes": 45,
        "work_type_id": None,
    }
    assert "title" not in event.payload
    assert "notes" not in event.payload
