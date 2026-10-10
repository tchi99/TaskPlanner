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


    def save(self, task: Task) -> Task:
        record = self._session.get(TaskRecord, str(task.id))
        if record is None:
            raise LookupError("task not found")
        record.title = task.title
        record.project_id = str(task.project_id) if task.project_id else None
        record.notes = task.notes
        record.status = task.status.value
        record.protection = task.protection.value
        record.work_type_id = str(task.work_type_id) if task.work_type_id else None
        record.estimated_minutes = task.estimated_minutes
        record.due_at = task.due_at
        # created_at and id are intentionally immutable.
        self._session.flush()
        return task

    def save_aggregate(self, aggregate: TaskAggregate) -> TaskAggregate:
        """Persist a whole Task aggregate without destructive ORM cascades.

        Stage existing rows at unused positions before their final placement:
        SQLite enforces UNIQUE(task_id, position) on every UPDATE, including
        ordinary two-row swaps.
        """
        self.save(aggregate.task)
        existing = {
            record.id: record for record in self._session.scalars(
                select(TaskSegmentRecord).where(
                    TaskSegmentRecord.task_id == str(aggregate.task.id)
                )
            ).all()
        }
        target = {str(segment.id): segment for segment in aggregate.segments}
        for key, record in existing.items():
            if key not in target:
                self._session.delete(record)
        self._session.flush()

        staging = max(
            [record.position for record in existing.values()]
            + [segment.position for segment in aggregate.segments]
            + [-1]
        ) + 1
        for index, (key, record) in enumerate(existing.items()):
            if key in target:
                record.position = staging + index
        self._session.flush()

        for segment in aggregate.segments:
            record = existing.get(str(segment.id))
            if record is None:
                self._session.add(self._segment_record(segment))
                continue
            record.title = segment.title
            record.status = segment.status.value
            record.position = segment.position
            record.estimated_minutes = segment.estimated_minutes
            record.work_type_id = (
                str(segment.work_type_id) if segment.work_type_id else None
            )
            record.protection_override = (
                segment.protection_override.value if segment.protection_override else None
            )
        self._session.flush()
        return aggregate

    def list_all(self) -> list[Task]:
        records = self._session.scalars(
            select(TaskRecord).order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
        ).all()
        return [self._to_domain(record) for record in records]

    def list_by_project(self, project_id: UUID | None) -> list[Task]:
        query = select(TaskRecord)
        if project_id is None:
            query = query.where(TaskRecord.project_id.is_(None))
        else:
            query = query.where(TaskRecord.project_id == str(project_id))
        records = self._session.scalars(
            query.order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
        ).all()
        return [self._to_domain(record) for record in records]

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
            protection_override=(segment.protection_override.value if segment.protection_override else None),
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
            protection_override=(
                ProtectionLevel(record.protection_override) if record.protection_override else None
            ),
        )
