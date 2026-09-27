from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import (
    ProtectionLevel,
    SegmentStatus,
    Task,
    TaskAggregate,
    TaskSegment,
    TaskStatus,
)
from app.infrastructure.models import TaskRecord, TaskSegmentRecord


class SqlTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: Task) -> Task:
        self._session.add(self._record(task))
        return task

    def get(self, task_id: UUID) -> Task | None:
        record = self._session.get(TaskRecord, str(task_id))
        return self._to_domain(record) if record else None

    def add_aggregate(self, aggregate: TaskAggregate) -> TaskAggregate:
        self.add(aggregate.task)
        # The task must exist before child rows are flushed because we avoid
        # ORM ownership/cascade semantics for this aggregate.
        self._session.flush()
        self._session.add_all(
            self._segment_record(segment) for segment in aggregate.segments
        )
        return aggregate

    def get_aggregate(self, task_id: UUID) -> TaskAggregate | None:
        task = self.get(task_id)
        if task is None:
            return None
        records = self._session.scalars(
            select(TaskSegmentRecord)
            .where(TaskSegmentRecord.task_id == str(task_id))
            .order_by(TaskSegmentRecord.position)
        ).all()
        segments = tuple(self._segment_to_domain(record) for record in records)
        return TaskAggregate(task, segments)

    def list_inbox(self) -> list[Task]:
        records = self._session.scalars(
            select(TaskRecord)
            .where(TaskRecord.status == TaskStatus.INBOX.value)
            .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
        ).all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _record(task: Task) -> TaskRecord:
        return TaskRecord(
            id=str(task.id),
            title=task.title,
            project_id=str(task.project_id) if task.project_id else None,
            notes=task.notes,
            status=task.status.value,
            protection=task.protection.value,
            work_type_id=(str(task.work_type_id) if task.work_type_id else None),
            estimated_minutes=task.estimated_minutes,
            due_at=task.due_at,
            created_at=task.created_at,
        )

    @staticmethod
    def _segment_record(segment: TaskSegment) -> TaskSegmentRecord:
        return TaskSegmentRecord(
            id=str(segment.id),
            task_id=str(segment.task_id),
            title=segment.title,
            status=segment.status.value,
            position=segment.position,
            work_type_id=(
                str(segment.work_type_id) if segment.work_type_id else None
            ),
            estimated_minutes=segment.estimated_minutes,
        )

    @staticmethod
    def _to_domain(record: TaskRecord) -> Task:
        return Task(
            id=UUID(record.id),
            title=record.title,
            project_id=UUID(record.project_id) if record.project_id else None,
            notes=record.notes,
            status=TaskStatus(record.status),
            protection=ProtectionLevel(record.protection),
            work_type_id=(UUID(record.work_type_id) if record.work_type_id else None),
            estimated_minutes=record.estimated_minutes,
            due_at=record.due_at,
            created_at=record.created_at,
        )

    @staticmethod
    def _segment_to_domain(record: TaskSegmentRecord) -> TaskSegment:
        return TaskSegment(
            id=UUID(record.id),
            task_id=UUID(record.task_id),
            title=record.title,
            status=SegmentStatus(record.status),
            position=record.position,
            work_type_id=(
                UUID(record.work_type_id) if record.work_type_id else None
            ),
            estimated_minutes=record.estimated_minutes,
        )
