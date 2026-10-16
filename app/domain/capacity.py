"""Deterministic, calendar-independent weekly availability and feasibility."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Sequence
from uuid import UUID, uuid4

from app.domain.model import SegmentStatus, TaskStatus
from app.domain.task_rules import TaskAggregate


def validate_week_start(week_start: date) -> None:
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")


@dataclass(frozen=True, slots=True)
class AvailabilityBlock:
    week_start: date
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    scope_id: UUID | None = None

    def __post_init__(self) -> None:
        validate_week_start(self.week_start)
        for name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            if value.second or value.microsecond:
                raise ValueError(f"{name} must align to a whole minute")
        end_of_week = self.week_start + timedelta(days=7)
        if not self.week_start <= self.starts_at.date() < end_of_week:
            raise ValueError("starts_at must be inside the selected local week")
        if not (
            self.week_start <= self.ends_at.date() < end_of_week
            or (self.ends_at.date() == end_of_week
                and self.ends_at.hour == 0 and self.ends_at.minute == 0)
        ):
            raise ValueError("ends_at must be inside the selected local week")
        if self.ends_at.astimezone(timezone.utc) <= self.starts_at.astimezone(timezone.utc):
            raise ValueError("ends_at must be after starts_at")

    @property
    def minutes(self) -> int:
        duration = self.ends_at.astimezone(timezone.utc) - self.starts_at.astimezone(timezone.utc)
        return int(duration.total_seconds() // 60)


def validate_blocks(week_start: date, blocks: Sequence[AvailabilityBlock]) -> None:
    validate_week_start(week_start)
    ordered = sorted(blocks, key=lambda b: b.starts_at.astimezone(timezone.utc))
    for block in ordered:
        if block.week_start != week_start:
            raise ValueError("availability block belongs to another week")
    for previous, current in zip(ordered, ordered[1:]):
        if previous.ends_at.astimezone(timezone.utc) > current.starts_at.astimezone(timezone.utc):
            raise ValueError("availability blocks must not overlap")


class CapacityStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    INCOMPLETE = "INCOMPLETE"
    OVER_CAPACITY = "OVER_CAPACITY"


@dataclass(frozen=True, slots=True)
class WorkTypeCapacity:
    work_type_id: UUID | None
    available_minutes: int
    known_demand_minutes: int
    unestimated_units: int
    remaining_minutes: int
    status: CapacityStatus
    scope_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WeeklyCapacityEvaluation:
    week_start: date
    available_minutes: int
    known_demand_minutes: int
    unestimated_units: int
    remaining_minutes: int
    status: CapacityStatus
    by_work_type: tuple[WorkTypeCapacity, ...]


def evaluate_week(
    week_start: date,
    blocks: Sequence[AvailabilityBlock],
    candidates: Sequence[TaskAggregate],
) -> WeeklyCapacityEvaluation:
    """Evaluate a hypothetical selection; no plan is accepted or written.

    NULL work type is its own 'unclassified' bucket, not an unrestricted
    pool that can be counted again for each classified work type.
    """
    validate_blocks(week_start, blocks)
    # Legacy evaluation retains its flat WorkType/NULL contract when there
    # is only one parent. Across parents the buckets must be disjoint, and an
    # unclassified task may not borrow either parent's residual NULL minutes.
    scoped = len({b.scope_id for b in blocks}) > 1
    available: dict[object, int] = {}
    demand: dict[object, int] = {}
    unknown: dict[object, int] = {}
    for block in blocks:
        key = (block.scope_id, block.work_type_id) if scoped else block.work_type_id
        available[key] = available.get(key, 0) + block.minutes
    by_type = {}
    if scoped:
        for scope_id, work_type in available:
            by_type.setdefault(work_type, set()).add(scope_id)

    def bucket(work_type_id):
        if not scoped:
            return work_type_id
        if work_type_id is None:
            return (None, None)
        scopes = by_type.get(work_type_id, set())
        return (next(iter(scopes)), work_type_id) if len(scopes) == 1 else (None, work_type_id)

    ids: set[UUID] = set()
    for aggregate in candidates:
        task = aggregate.task
        if task.id in ids:
            raise ValueError("candidate tasks must be unique")
        ids.add(task.id)
        if task.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            raise ValueError("only open clarified tasks may be evaluated")
        active = [
            segment for segment in aggregate.segments
            if segment.status in {SegmentStatus.TODO, SegmentStatus.IN_PROGRESS}
        ]
        if active:
            units = [
                (aggregate.effective_segment_work_type(s.id).work_type_id, s.estimated_minutes)
                for s in active
            ]
        elif aggregate.segments:
            # All segments have closed; parent estimate is not unfinished work.
            units = []
        else:
            units = [(task.work_type_id, task.estimated_minutes)]
        for work_type_id, estimate in units:
            key = bucket(work_type_id)
            if estimate is None:
                unknown[key] = unknown.get(key, 0) + 1
            else:
                demand[key] = demand.get(key, 0) + estimate

    buckets = []
    for key in sorted(
        set(available) | set(demand) | set(unknown),
        key=lambda value: (str(value) if scoped else (str(value is not None) + str(value or ""))),
    ):
        scope_id, work_type_id = key if scoped else (None, key)
        capacity = available.get(key, 0)
        known = demand.get(key, 0)
        missing = unknown.get(key, 0)
        status = (
            CapacityStatus.OVER_CAPACITY if known > capacity
            else CapacityStatus.INCOMPLETE if missing
            else CapacityStatus.FEASIBLE
        )
        buckets.append(WorkTypeCapacity(
            work_type_id=work_type_id,
            available_minutes=capacity,
            known_demand_minutes=known,
            unestimated_units=missing,
            remaining_minutes=capacity - known,
            status=status, scope_id=scope_id,
        ))

    status = (
        CapacityStatus.OVER_CAPACITY
        if any(bucket.status is CapacityStatus.OVER_CAPACITY for bucket in buckets)
        else CapacityStatus.INCOMPLETE
        if any(bucket.status is CapacityStatus.INCOMPLETE for bucket in buckets)
        else CapacityStatus.FEASIBLE
    )
    return WeeklyCapacityEvaluation(
        week_start=week_start,
        available_minutes=sum(b.available_minutes for b in buckets),
        known_demand_minutes=sum(b.known_demand_minutes for b in buckets),
        unestimated_units=sum(b.unestimated_units for b in buckets),
        remaining_minutes=sum(b.remaining_minutes for b in buckets),
        status=status,
        by_work_type=tuple(buckets),
    )
