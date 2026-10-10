"""SQL persistence for explicit work sessions (no autonomous commits)."""
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.work_sessions import SessionConflict, SessionStatus, WorkSession
from app.infrastructure.models import WorkSessionRecord


class SqlWorkSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _domain(row: WorkSessionRecord) -> WorkSession:
        return WorkSession(
            id=UUID(row.id), task_id=UUID(row.task_id),
            segment_id=UUID(row.segment_id) if row.segment_id else None,
            started_at=row.started_at, active_since=row.active_since,
            finished_at=row.finished_at, active_seconds=row.active_seconds,
            interruptions=row.interruptions, status=SessionStatus(row.status),
            revision=row.revision,
            work_type_id=UUID(row.work_type_id) if row.work_type_id else None,
            estimated_minutes=row.estimated_minutes, planned_minutes=row.planned_minutes,
        )

    def add(self, value: WorkSession) -> None:
        self._session.add(WorkSessionRecord(
            id=str(value.id), task_id=str(value.task_id),
            segment_id=str(value.segment_id) if value.segment_id else None,
            started_at=value.started_at, active_since=value.active_since,
            finished_at=value.finished_at, active_seconds=value.active_seconds,
            interruptions=value.interruptions, status=value.status.value,
            revision=value.revision,
            work_type_id=str(value.work_type_id) if value.work_type_id else None,
            estimated_minutes=value.estimated_minutes, planned_minutes=value.planned_minutes,
        ))
        self._session.flush()

    def get(self, session_id: UUID) -> WorkSession | None:
        row = self._session.get(WorkSessionRecord, str(session_id))
        return self._domain(row) if row else None

    def get_active(self) -> WorkSession | None:
        row = self._session.scalars(select(WorkSessionRecord).where(
            WorkSessionRecord.status == SessionStatus.ACTIVE.value
        )).first()
        return self._domain(row) if row else None

    def list_task(self, task_id: UUID) -> list[WorkSession]:
        rows = self._session.scalars(select(WorkSessionRecord).where(
            WorkSessionRecord.task_id == str(task_id)
        ).order_by(WorkSessionRecord.started_at, WorkSessionRecord.id)).all()
        return [self._domain(row) for row in rows]

    def list_all(self) -> list[WorkSession]:
        return [self._domain(row) for row in self._session.scalars(
            select(WorkSessionRecord).order_by(WorkSessionRecord.started_at)
        ).all()]

    def save(self, value: WorkSession, expected_revision: int) -> None:
        result = self._session.execute(
            update(WorkSessionRecord)
            .where(WorkSessionRecord.id == str(value.id),
                   WorkSessionRecord.revision == expected_revision)
            .values(status=value.status.value, active_since=value.active_since,
                    finished_at=value.finished_at, active_seconds=value.active_seconds,
                    interruptions=value.interruptions, revision=value.revision)
        )
        if result.rowcount != 1:
            raise SessionConflict("session revision changed; reload before updating")
        self._session.flush()
