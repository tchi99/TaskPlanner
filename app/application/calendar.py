"""Fetch ephemeral calendar context and compare with manual capacity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.uow import UnitOfWork
from app.application.planning_availability import effective_week
from app.domain.calendar import (
    CalendarCapacity, CalendarCommitment, calculate_calendar_capacity,
)
from app.domain.capacity import validate_week_start


class CalendarReader(Protocol):
    def list_commitments(
        self, starts_at: datetime, ends_at: datetime, timezone_name: str
    ) -> Sequence[CalendarCommitment]: ...


@dataclass(frozen=True, slots=True)
class CalendarWeek:
    timezone_name: str
    capacity: CalendarCapacity
    commitments: tuple[CalendarCommitment, ...]


def read_calendar_week(
    uow: UnitOfWork, reader: CalendarReader, week_start: date, timezone_name: str
) -> CalendarWeek:
    validate_week_start(week_start)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    start = datetime.combine(week_start, time.min, tzinfo=zone)
    # A local civil week can have 167 or 169 hours across DST.
    end = datetime.combine(week_start + timedelta(days=7), time.min, tzinfo=zone)
    commitments = tuple(sorted(
        reader.list_commitments(start, end, timezone_name),
        key=lambda event: (event.starts_at, event.calendar_id, event.event_id),
    ))
    with uow:
        manual_blocks = effective_week(
            uow, "urn:taskplanner:local", week_start, timezone_name).blocks
    return CalendarWeek(
        timezone_name=timezone_name,
        capacity=calculate_calendar_capacity(week_start, manual_blocks, commitments),
        commitments=commitments,
    )
