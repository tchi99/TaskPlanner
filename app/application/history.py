from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Iterable
from uuid import UUID, uuid4

from app.domain import (
    DomainFact,
    EstimateChanged,
    FactRole,
    SegmentPosition,
    SegmentStatusChanged,
    TaskCaptured,
    TaskStatusChanged,
    WorkTypeChanged,
)


class HistorySource(StrEnum):
    USER = "USER"
    SYSTEM_RULE = "SYSTEM_RULE"
    IMPORT = "IMPORT"
    AI = "AI"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("history timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    id: UUID
    occurred_at: datetime
    recorded_at: datetime
    entity_type: str
    entity_id: UUID
    task_id: UUID | None
    event_type: str
    schema_version: int
    source: HistorySource
    reason_code: str | None
    correlation_id: UUID
    causation_id: UUID | None
    payload: dict[str, object | None]
    sequence: int | None = field(default=None)

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be greater than zero")
        to_utc(self.occurred_at)
        to_utc(self.recorded_at)


Clock = Callable[[], datetime]


def serialize_fact_payload(fact: DomainFact) -> dict[str, object | None]:
    payload = fact.payload
    if payload is None:
        return {}
    if isinstance(payload, TaskCaptured):
        return {
            "status": payload.status.value,
            "estimated_minutes": payload.estimated_minutes,
            "work_type_id": str(payload.work_type_id) if payload.work_type_id else None,
        }
    if isinstance(payload, TaskStatusChanged):
        return {"before": payload.before.value, "after": payload.after.value}
    if isinstance(payload, SegmentStatusChanged):
        return {"before": payload.before.value, "after": payload.after.value}
    if isinstance(payload, EstimateChanged):
        return {"before": payload.before, "after": payload.after}
    if isinstance(payload, WorkTypeChanged):
        return {
            "before": str(payload.before) if payload.before else None,
            "after": str(payload.after) if payload.after else None,
        }
    if isinstance(payload, SegmentPosition):
        return {"position": payload.position}
    raise TypeError(f"unsupported history payload: {type(payload).__name__}")


def build_history_events(
    facts: Iterable[DomainFact],
    *,
    direct_source: HistorySource,
    reason_code: str | None = None,
    correlation_id: UUID | None = None,
    occurred_at: datetime | None = None,
    clock: Clock = _utc_now,
) -> tuple[HistoryEvent, ...]:
    correlation = correlation_id or uuid4()
    happened_at = to_utc(occurred_at or clock())
    recorded_at = to_utc(clock())
    events: list[HistoryEvent] = []
    last_direct_event_id: UUID | None = None

    for fact in facts:
        event_id = uuid4()
        if fact.role is FactRole.DIRECT:
            source = direct_source
            causation_id = None
            last_direct_event_id = event_id
        else:
            source = HistorySource.SYSTEM_RULE
            causation_id = last_direct_event_id
        events.append(
            HistoryEvent(
                id=event_id,
                occurred_at=happened_at,
                recorded_at=recorded_at,
                entity_type=fact.entity_type.value,
                entity_id=fact.entity_id,
                task_id=fact.task_id,
                event_type=fact.event_type.value,
                schema_version=fact.schema_version,
                source=source,
                reason_code=reason_code,
                correlation_id=correlation,
                causation_id=causation_id,
                payload=serialize_fact_payload(fact),
            )
        )
    return tuple(events)
