from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.application.history import HistoryEvent
from app.infrastructure.models import HistoryEventRecord


class SqlHistoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_task_interactions(self, before: datetime) -> dict[UUID, datetime]:
        rows = self._session.execute(
            select(HistoryEventRecord.task_id, func.max(HistoryEventRecord.recorded_at))
            .where(HistoryEventRecord.task_id.is_not(None),
                   HistoryEventRecord.recorded_at < before)
            .group_by(HistoryEventRecord.task_id)
        ).all()
        return {UUID(task_id): timestamp for task_id, timestamp in rows}

    def append(self, event: HistoryEvent) -> None:
        self._session.add(
            HistoryEventRecord(
                id=str(event.id),
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                entity_type=event.entity_type,
                entity_id=str(event.entity_id),
                task_id=str(event.task_id) if event.task_id else None,
                event_type=event.event_type,
                schema_version=event.schema_version,
                source=event.source.value,
                reason_code=event.reason_code,
                correlation_id=str(event.correlation_id),
                causation_id=(
                    str(event.causation_id) if event.causation_id else None
                ),
                payload=event.payload,
            )
        )

    def append_many(self, events: Sequence[HistoryEvent]) -> None:
        for event in events:
            self.append(event)
