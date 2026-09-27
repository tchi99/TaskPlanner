from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from .model import SegmentStatus, TaskStatus


class DomainFactType(StrEnum):
    TASK_CLARIFIED = "TASK_CLARIFIED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_REOPENED = "TASK_REOPENED"
    TASK_ESTIMATE_CHANGED = "TASK_ESTIMATE_CHANGED"
    TASK_WORK_TYPE_CHANGED = "TASK_WORK_TYPE_CHANGED"
    SEGMENT_ADDED = "SEGMENT_ADDED"
    SEGMENT_STARTED = "SEGMENT_STARTED"
    SEGMENT_COMPLETED = "SEGMENT_COMPLETED"
    SEGMENT_CANCELLED = "SEGMENT_CANCELLED"
    SEGMENT_REMOVED = "SEGMENT_REMOVED"
    SEGMENT_ESTIMATE_CHANGED = "SEGMENT_ESTIMATE_CHANGED"
    SEGMENT_WORK_TYPE_CHANGED = "SEGMENT_WORK_TYPE_CHANGED"


class DomainEntityType(StrEnum):
    TASK = "TASK"
    SEGMENT = "SEGMENT"


class FactRole(StrEnum):
    DIRECT = "DIRECT"
    PROPAGATED = "PROPAGATED"


@dataclass(frozen=True, slots=True)
class TaskStatusChanged:
    before: TaskStatus
    after: TaskStatus


@dataclass(frozen=True, slots=True)
class SegmentStatusChanged:
    before: SegmentStatus
    after: SegmentStatus


@dataclass(frozen=True, slots=True)
class EstimateChanged:
    before: int | None
    after: int | None


@dataclass(frozen=True, slots=True)
class WorkTypeChanged:
    before: UUID | None
    after: UUID | None


@dataclass(frozen=True, slots=True)
class SegmentPosition:
    position: int


FactPayload = (
    TaskStatusChanged
    | SegmentStatusChanged
    | EstimateChanged
    | WorkTypeChanged
    | SegmentPosition
    | None
)


@dataclass(frozen=True, slots=True)
class DomainFact:
    event_type: DomainFactType
    entity_type: DomainEntityType
    entity_id: UUID
    task_id: UUID
    role: FactRole
    payload: FactPayload = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be greater than zero")


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MutationResult(Generic[T]):
    value: T
    facts: tuple[DomainFact, ...] = ()
