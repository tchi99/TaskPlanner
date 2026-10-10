"""Read-only projection of occupied time against explicitly declared capacity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import ceil
from typing import Sequence
from uuid import UUID

from app.domain.capacity import AvailabilityBlock, validate_blocks


@dataclass(frozen=True, slots=True)
class CalendarCommitment:
    calendar_id: str
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if any(
            dt.tzinfo is None or dt.utcoffset() is None
            for dt in (self.starts_at, self.ends_at)
        ):
            raise ValueError("calendar event timestamps must be timezone-aware")
        if self.ends_at.astimezone(timezone.utc) <= self.starts_at.astimezone(timezone.utc):
            raise ValueError("calendar event end must follow its start")


@dataclass(frozen=True, slots=True)
class CalendarCapacityBucket:
    work_type_id: UUID | None
    manual_available_minutes: int
    occupied_minutes: int
    remaining_minutes: int


@dataclass(frozen=True, slots=True)
class CalendarCapacity:
    week_start: date
    manual_available_minutes: int
    occupied_minutes: int
    remaining_minutes: int
    by_work_type: tuple[CalendarCapacityBucket, ...]


def _occupied_minutes(
    block: AvailabilityBlock, commitments: Sequence[CalendarCommitment]
) -> int:
    """Union event intervals, clipped to this block, without double-counting."""
    start = block.starts_at.astimezone(timezone.utc)
    end = block.ends_at.astimezone(timezone.utc)
    spans = sorted(
        (
            max(start, event.starts_at.astimezone(timezone.utc)),
            min(end, event.ends_at.astimezone(timezone.utc)),
        )
        for event in commitments
        if event.starts_at.astimezone(timezone.utc) < end
        and event.ends_at.astimezone(timezone.utc) > start
    )
    seconds = 0.0
    left = right = None
    for first, last in spans:
        if left is None:
            left, right = first, last
        elif first <= right:
            right = max(right, last)
        else:
            seconds += (right - left).total_seconds()
            left, right = first, last
    if left is not None:
        seconds += (right - left).total_seconds()
    # A partial minute is not safely available for scheduling.
    return min(block.minutes, ceil(seconds / 60))


def calculate_calendar_capacity(
    week_start: date,
    manual_blocks: Sequence[AvailabilityBlock],
    commitments: Sequence[CalendarCommitment],
) -> CalendarCapacity:
    """Calendar is a constraint over manual blocks, never a task or extra capacity.

    No availability is assumed outside the user's manual blocks. All calendar
    times are compared as instants; local week selection is done by the caller.
    """
    validate_blocks(week_start, manual_blocks)
    buckets: dict[UUID | None, tuple[int, int]] = {}
    for block in manual_blocks:
        minutes = _occupied_minutes(block, commitments)
        available, occupied = buckets.get(block.work_type_id, (0, 0))
        buckets[block.work_type_id] = (available + block.minutes, occupied + minutes)
    values = tuple(
        CalendarCapacityBucket(work_type_id=key, manual_available_minutes=available,
                               occupied_minutes=occupied, remaining_minutes=available - occupied)
        for key, (available, occupied) in sorted(
            buckets.items(), key=lambda item: (item[0] is not None, str(item[0] or ""))
        )
    )
    return CalendarCapacity(
        week_start=week_start,
        manual_available_minutes=sum(item.manual_available_minutes for item in values),
        occupied_minutes=sum(item.occupied_minutes for item in values),
        remaining_minutes=sum(item.remaining_minutes for item in values),
        by_work_type=values,
    )
