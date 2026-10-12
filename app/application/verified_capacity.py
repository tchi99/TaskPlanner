"""Verified free capacity: effective declarations minus external/local occupancy.

Never fall back to an empty calendar. The read is advisory and does not lock
Google Calendar; confirmation re-reads it under a local planning transaction.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.calendar import CalendarReader
from app.application.planning_availability import effective_week
from app.application.uow import UnitOfWork
from app.domain.capacity import validate_week_start
from app.domain.time_blocks import _free_intervals


def verified_week(
    uow: UnitOfWork, reader: CalendarReader, owner_id: str,
    week_start: date, timezone_name: str,
) -> dict:
    validate_week_start(week_start)
    zone = ZoneInfo(timezone_name)
    starts_at = datetime.combine(week_start, time.min, tzinfo=zone)
    ends_at = datetime.combine(week_start + timedelta(days=7), time.min, tzinfo=zone)
    commitments = tuple(reader.list_commitments(starts_at, ends_at, timezone_name))
    with uow:
        state = effective_week(uow, owner_id, week_start, timezone_name)
        confirmed = tuple(uow.time_blocks.list_week(week_start))
        free = _free_intervals(state.blocks, commitments, confirmed)
        declared: dict[UUID | None, int] = {}
        for block in state.blocks:
            declared[block.work_type_id] = declared.get(block.work_type_id, 0) + block.minutes
        free_by_type = {
            kind: sum(end - start for start, end in spans)
            for kind, spans in free.items()
        }
        conflicts = [
            {
                "code": issue.code, "starts_at": issue.starts_at,
                "ends_at": issue.ends_at, "booking_id": issue.booking_id,
                "sources": issue.sources, "state": issue.state,
            }
            for issue in state.projection.issues
        ]
        for booking in confirmed:
            for event in commitments:
                start = max(booking.starts_at.astimezone(timezone.utc),
                            event.starts_at.astimezone(timezone.utc))
                end = min(booking.ends_at.astimezone(timezone.utc),
                          event.ends_at.astimezone(timezone.utc))
                if start < end:
                    conflicts.append({
                        "code": "BOOKING_CONFLICTS_WITH_GOOGLE",
                        "starts_at": start, "ends_at": end,
                        "booking_id": booking.id, "sources": (
                            f"BOOKING:{booking.id}",
                            f"GOOGLE:{event.calendar_id}:{event.event_id}",
                        ), "state": "OPEN",
                    })
        rows = [{
            "work_type_id": kind,
            "declared_minutes": declared[kind],
            "free_minutes": free_by_type.get(kind, 0),
        } for kind in sorted(declared, key=lambda v: (v is not None, str(v)))]
        return {
            "week_start": week_start, "timezone_name": timezone_name,
            "projection": "CALENDAR_CHECKED_NOT_RESERVED",
            "calendar_checked": True,
            "declared_minutes": sum(declared.values()),
            "free_minutes": sum(free_by_type.values()),
            "by_work_type": rows, "issues": conflicts,
            "expansion_issues": [{
                "rule_id": v.rule_id, "revision": v.revision,
                "original_local_date": v.original_local_date, "reason": v.reason,
            } for v in state.projection.expansion_issues],
        }
