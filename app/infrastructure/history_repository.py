from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.application.history import HistoryEvent
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
