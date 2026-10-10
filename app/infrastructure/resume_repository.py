"""Resume markers are local user notes, not semantic history events."""
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.start import ResumePoint
from app.domain.task_rules import NextActionType
from app.infrastructure.models import ResumePointRecord


class SqlResumePointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, task_id: UUID) -> ResumePoint | None:
        record = self._session.get(ResumePointRecord, str(task_id))
        if record is None:
            return None
        return ResumePoint(
            task_id=UUID(record.task_id),
            action_type=NextActionType(record.action_type),
            target_id=UUID(record.target_id),
            text=record.text,
            revision=record.revision,
            updated_at=record.updated_at,
        )

    def save(self, value: ResumePoint) -> None:
        record = self._session.get(ResumePointRecord, str(value.task_id))
        if record is None:
            self._session.add(ResumePointRecord(
                task_id=str(value.task_id),
                action_type=value.action_type.value,
                target_id=str(value.target_id),
                text=value.text,
                revision=value.revision,
                updated_at=value.updated_at,
            ))
        else:
            record.action_type = value.action_type.value
            record.target_id = str(value.target_id)
            record.text = value.text
            record.revision = value.revision
            record.updated_at = value.updated_at
        self._session.flush()
