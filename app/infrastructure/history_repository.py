from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.history import HistoryEvent, HistorySource
from app.infrastructure.models import HistoryEventRecord


class SqlHistoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

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

class SqlHistoryReadRepository:
    """Read-side projection; intentionally separate from append-only writes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self, before: datetime | None = None) -> list[HistoryEvent]:
        query = select(HistoryEventRecord)
        if before is not None:
            query = query.where(HistoryEventRecord.recorded_at <= before)
        rows = self._session.scalars(query.order_by(HistoryEventRecord.sequence)).all()
        return [HistoryEvent(
            id=UUID(row.id), occurred_at=row.occurred_at,
            recorded_at=row.recorded_at, entity_type=row.entity_type,
            entity_id=UUID(row.entity_id),
            task_id=UUID(row.task_id) if row.task_id else None,
            event_type=row.event_type, schema_version=row.schema_version,
            source=HistorySource(row.source), reason_code=row.reason_code,
            correlation_id=UUID(row.correlation_id),
            causation_id=UUID(row.causation_id) if row.causation_id else None,
            payload=row.payload, sequence=row.sequence,
        ) for row in rows]
