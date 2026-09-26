from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import ProtectionLevel, Task, TaskStatus
from app.infrastructure.models import TaskRecord


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class SqlTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: Task) -> Task:
        self._session.add(
            TaskRecord(
                id=str(task.id),
                title=task.title,
                project_id=str(task.project_id) if task.project_id else None,
                notes=task.notes,
                status=task.status.value,
                protection=task.protection.value,
                work_type_id=str(task.work_type_id) if task.work_type_id else None,
                estimated_minutes=task.estimated_minutes,
                due_at=task.due_at,
                created_at=task.created_at,
            )
        )
        self._session.commit()
        return task

    def list_inbox(self) -> list[Task]:
        records = self._session.scalars(
            select(TaskRecord)
            .where(TaskRecord.status == TaskStatus.INBOX.value)
            .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
        ).all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_domain(record: TaskRecord) -> Task:
        created_at = _aware(record.created_at)
        assert created_at is not None
        return Task(
            id=UUID(record.id),
            title=record.title,
            project_id=UUID(record.project_id) if record.project_id else None,
            notes=record.notes,
            status=TaskStatus(record.status),
            protection=ProtectionLevel(record.protection),
            work_type_id=UUID(record.work_type_id) if record.work_type_id else None,
            estimated_minutes=record.estimated_minutes,
            due_at=_aware(record.due_at),
            created_at=created_at,
        )
