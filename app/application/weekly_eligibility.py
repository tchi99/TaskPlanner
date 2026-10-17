"""TP-025C: read-only weekly visualization of the one physical eligibility timeline.

Display geometry is derived from UTC instants in the requested IANA zone. A
permission is never extra capacity, and an unchecked Google calendar is never
evidence that physical minutes are free.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.calendar import CalendarReader
from app.application.effective_availability import _state
from app.application.planning_availability import effective_week
from app.application.uow import UnitOfWork
from app.domain.capacity import validate_week_start
from app.domain.schedule_scopes import compatibility_scope_id
from app.domain.time_blocks import _free_intervals
from app.infrastructure.google_calendar import (
    GoogleCalendarNotConfigured, GoogleCalendarUnavailable,
)


def _instant(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _intersects(first: datetime, last: datetime, spans) -> bool:
    return any(first < end and last > start for start, end in spans)


def _day_pieces(start: datetime, end: datetime, zone: ZoneInfo, week: date):
    """Split at civil midnights while measuring elapsed UTC, not wall hours."""
    cursor = _instant(start)
    end = _instant(end)
    while cursor < end:
        day = cursor.astimezone(zone).date()
        midnight = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
        next_midnight = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        stop = min(end, next_midnight)
        if stop <= cursor:
            raise ValueError("invalid civil-day boundary")
        yield {
            "starts_at": cursor,
            "ends_at": stop,
            "starts_at_local": cursor.astimezone(zone).isoformat(),
            "ends_at_local": stop.astimezone(zone).isoformat(),
            "local_date": day,
            "weekday": (day - week).days,
            "start_minute": int((cursor - midnight).total_seconds() // 60),
            "end_minute": int((stop - midnight).total_seconds() // 60),
            "day_minutes": int((next_midnight - midnight).total_seconds() // 60),
            "minutes": int((stop - cursor).total_seconds() // 60),
        }
        cursor = stop




def _civil_day(week: date, offset: int, zone: ZoneInfo) -> dict:
    """Wall-clock labels backed by elapsed UTC minutes, including DST days."""
    day = week + timedelta(days=offset)
    begin = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    minutes = int((end - begin).total_seconds() // 60)
    ticks = [{
        "label": f"{hour:02d}:00",
        "minute": int((datetime.combine(day, time(hour=hour), zone).astimezone(
            timezone.utc) - begin).total_seconds() // 60),
    } for hour in (0, 6, 12, 18)]
    ticks.append({"label": "Fin", "minute": minutes})
    return {
        "local_date": day, "weekday": offset, "starts_at": begin,
        "ends_at": end, "minutes": minutes, "ticks": ticks,
    }


def _choice_details(choice, series_by_id: dict[str, object]) -> dict:
    details = []
    for source in choice.sources:
        if not source.startswith("ELIGIBILITY:"):
            continue
        parts = source.split(":")
        if len(parts) < 4:
            continue
        series = series_by_id.get(parts[1])
        if series is None:
            continue
        number = parts[3]
        if not number.startswith("v") or not number[1:].isdigit():
            continue
        revision = next((item for item in series.revisions
                         if item.number == int(number[1:])), None)
        if revision is not None:
            details.append({
                "series_id": series.id, "revision": revision.number,
                "effective_from": revision.effective_from,
                "valid_until": revision.valid_until,
                "timezone_name": revision.timezone_name,
                "original_local_date": parts[2],
                "source": source,
            })
    return {
        "work_type_id": choice.work_type_id,
        "priority_rank": choice.priority_rank,
        "exclusive": choice.exclusive,
        "legacy_mode": choice.legacy_mode,
        "sources": choice.sources,
        "source_details": details,
    }


def weekly_eligibility(
    uow: UnitOfWork, reader: CalendarReader, owner_id: str,
    week_start: date, timezone_name: str, scope_id: UUID | None = None,
) -> dict:
    """Owner-scoped, non-mutating projection. A failed Google read fails closed."""
    validate_week_start(week_start)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    selected = scope_id or compatibility_scope_id(owner_id)
    start = datetime.combine(week_start, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(week_start + timedelta(days=7), time.min, zone).astimezone(timezone.utc)
    calendar_state = "VERIFIED"
    calendar_error = None
    try:
        commitments = tuple(reader.list_commitments(start, end, timezone_name))
    except GoogleCalendarNotConfigured:
        commitments = ()
        calendar_state = "NOT_CONFIGURED"
        calendar_error = "Google Calendar n'est pas configuré : disponibilité non vérifiée."
    except GoogleCalendarUnavailable:
        commitments = ()
        calendar_state = "UNAVAILABLE"
        calendar_error = "Google Calendar est indisponible : disponibilité non vérifiée."

    with uow:
        owned_scopes = tuple(uow.schedule_scopes.list_owner(owner_id))
        if selected != compatibility_scope_id(owner_id) and not any(
                item.id == selected for item in owned_scopes):
            raise LookupError("schedule scope not found")
        state = effective_week(uow, owner_id, week_start, timezone_name)
        _, _, _, all_bookings = _state(
            uow, owner_id, week_start, week_start + timedelta(days=7))
        confirmed = tuple({item.id: item for item in all_bookings
                           if item.status == "CONFIRMED"}.values())
        series = {str(item.id): item for item in uow.eligibility.list_owner(owner_id)}
        fragments = tuple(item for item in state.eligibility.fragments
                          if item.scope_id == selected)
        physical = tuple(item for item in state.blocks if item.scope_id == selected)
        spans = tuple((item.starts_at, item.ends_at) for item in fragments)
        visible_bookings = tuple(item for item in confirmed
                                 if (item.scope_id or compatibility_scope_id(owner_id)) == selected
                                 and _intersects(_instant(item.starts_at),
                                                 _instant(item.ends_at), spans))
        # Google busy time is global; clip to this parent's declared physical time.
        visible_events = tuple(item for item in commitments
                               if _intersects(_instant(item.starts_at),
                                              _instant(item.ends_at), spans))
        physical_minutes = sum(item.minutes for item in fragments)
        # Existing allocator's UTC half-open interval subtraction is authoritative
        # for confirmed bookings and conservative Google busy cuts.
        local_free = sum(hi - lo for intervals in _free_intervals(
            physical, (), confirmed).values() for lo, hi in intervals)
        checked_free = (sum(hi - lo for intervals in _free_intervals(
            physical, commitments, confirmed).values() for lo, hi in intervals)
            if calendar_state == "VERIFIED" else None)
        alternatives: dict[UUID, int] = {}
        for item in fragments:
            for choice in item.choices:
                if choice.work_type_id is not None:
                    alternatives[choice.work_type_id] = (
                        alternatives.get(choice.work_type_id, 0) + item.minutes)
        bars = []
        for item in fragments:
            for piece in _day_pieces(item.starts_at, item.ends_at, zone, week_start):
                bars.append({
                    **piece, "scope_id": item.scope_id,
                    "sources": item.sources, "null_residual": item.null_residual,
                    "choices": [_choice_details(choice, series) for choice in item.choices],
                    "verification": "DECLARED_ONLY",
                })
        occupations = []
        for booking in visible_bookings:
            for fragment in fragments:
                lo = max(_instant(booking.starts_at), fragment.starts_at)
                hi = min(_instant(booking.ends_at), fragment.ends_at)
                if lo < hi:
                    for piece in _day_pieces(lo, hi, zone, week_start):
                        occupations.append({
                            **piece, "kind": "LOCAL_CONFIRMED", "booking_id": booking.id,
                            "work_type_id": booking.work_type_id,
                            "task_id": booking.task_id,
                            "scope_id": selected, "source": f"BOOKING:{booking.id}",
                        })
        if calendar_state == "VERIFIED":
            for event in visible_events:
                for fragment in fragments:
                    lo = max(_instant(event.starts_at), fragment.starts_at)
                    hi = min(_instant(event.ends_at), fragment.ends_at)
                    if lo < hi:
                        for piece in _day_pieces(lo, hi, zone, week_start):
                            occupations.append({
                                **piece, "kind": "GOOGLE_VERIFIED", "scope_id": selected,
                                "source": f"GOOGLE:{event.calendar_id}:{event.event_id}",
                                "title": event.title,
                            })
        issues = [
            {
                "code": issue.code, "starts_at": issue.starts_at,
                "ends_at": issue.ends_at, "sources": issue.sources,
                "scope_ids": issue.scope_ids,
                "booking_id": issue.booking_id, "state": issue.state,
            }
            for issue in state.eligibility.issues
            if (selected in issue.scope_ids if issue.scope_ids
                else _intersects(issue.starts_at, issue.ends_at, spans))
        ]
        # Cross-source overlap stays visible; it is not another capacity bucket.
        if calendar_state == "VERIFIED":
            for booking in visible_bookings:
                for event in visible_events:
                    lo = max(_instant(booking.starts_at), _instant(event.starts_at))
                    hi = min(_instant(booking.ends_at), _instant(event.ends_at))
                    if lo < hi and _intersects(lo, hi, spans):
                        issues.append({
                            "code": "BOOKING_CONFLICTS_WITH_GOOGLE",
                            "starts_at": lo, "ends_at": hi,
                            "sources": (f"BOOKING:{booking.id}",
                                        f"GOOGLE:{event.calendar_id}:{event.event_id}"),
                            "scope_ids": (selected,), "booking_id": booking.id,
                            "state": "OPEN",
                        })
        expansion_issues = [{
            "code": issue.code, "series_id": issue.series_id,
            "original_local_date": issue.original_local_date,
        } for issue in state.eligibility.expansion_issues
            if str(issue.series_id) in series
            and series[str(issue.series_id)].scope_id == selected]
        return {
            "week_start": week_start, "timezone_name": timezone_name,
            "days": [_civil_day(week_start, offset, zone) for offset in range(7)],
            "scope_id": selected, "read_only": True,
            "projection": "PHYSICAL_ELIGIBILITY_NON_ADDITIVE",
            "revision_fingerprint": state.revision_fingerprint,
            "calendar_state": calendar_state,
            "calendar_checked": calendar_state == "VERIFIED",
            "calendar_error": calendar_error,
            "physical_minutes": physical_minutes,
            "potential_minutes": [
                {"work_type_id": work_type, "minutes": minutes, "non_additive": True}
                for work_type, minutes in sorted(alternatives.items(), key=lambda pair: str(pair[0]))
            ],
            "local_occupied_minutes": physical_minutes - local_free,
            "verified_occupied_minutes": (
                physical_minutes - checked_free if checked_free is not None else None),
            "verified_free_minutes": checked_free,
            "fragments": bars,
            "occupations": occupations,
            "issues": issues,
            "expansion_issues": expansion_issues,
            "proposal_state": "NOT_REQUESTED",
        }
