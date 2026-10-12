"""TP-022R: previewed, explicit, atomic decisions about *local* bookings.

Availability changes never invoke these commands. Google Calendar is read only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.application.calendar import CalendarReader
from app.application.effective_availability import _state
from app.application.history import HistoryEvent, HistorySource
from app.application.planning_availability import effective_week
from app.application.time_blocks import _window
from app.application.uow import UnitOfWork
from app.domain.model import SegmentStatus, TaskStatus
from app.domain.recurring_availability import AvailabilityMode
from app.domain.time_blocks import ConfirmedTimeBlock

Decision = Literal["CANCEL", "MOVE", "KEEP"]


class StaleBookingResolution(Exception):
    """Local booking or its applicable constraints changed."""


@dataclass(frozen=True, slots=True)
class ResolutionPreview:
    booking: ConfirmedTimeBlock
    decision: Decision
    fingerprint: str
    conflict_codes: tuple[str, ...]
    replacement: ConfirmedTimeBlock | None
    calendar_checked: bool
    consequences: tuple[str, ...]


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _overlaps(a: datetime, b: datetime, c: datetime, d: datetime) -> bool:
    return _utc(a) < _utc(d) and _utc(c) < _utc(b)


def _covered(candidate: ConfirmedTimeBlock, projection) -> bool:
    """Require the entire destination to be within compatible declarations."""
    cursor = _utc(candidate.starts_at)
    limit = _utc(candidate.ends_at)
    spans = sorted((
        b for b in projection.projection.blocks
        if b.work_type_id == candidate.work_type_id
        or (candidate.transferred_from is not None
            and b.work_type_id == candidate.transferred_from
            and b.mode is AvailabilityMode.PREFERRED)
    ), key=lambda b: b.starts_at)
    for span in spans:
        start, end = _utc(span.starts_at), _utc(span.ends_at)
        if start <= cursor < end:
            cursor = max(cursor, end)
            if cursor >= limit:
                return True
    return False


def _prepare(
    uow: UnitOfWork, reader: CalendarReader, owner: str,
    week: date, booking_id: UUID, revision: int, decision: Decision,
    zone_name: str, reason: str,
    starts_at: datetime | None, ends_at: datetime | None,
) -> ResolutionPreview:
    _window(week, zone_name)
    booking = uow.time_blocks.get(booking_id)
    if booking is None or booking.week_start != week:
        raise LookupError("local booking not found")
    if booking.status != "CONFIRMED" or booking.revision != revision:
        raise StaleBookingResolution("booking changed; reload and preview again")
    if not reason.strip():
        raise ValueError("reason is required")
    if decision != "MOVE" and (starts_at is not None or ends_at is not None):
        raise ValueError("only MOVE accepts replacement times")
    if decision == "MOVE" and (starts_at is None or ends_at is None):
        raise ValueError("MOVE needs replacement times")

    source = effective_week(uow, owner, week, zone_name)
    issues = tuple(v for v in source.projection.issues if v.booking_id == booking_id)
    codes = [v.code for v in issues]
    calendar_checked = decision != "CANCEL"
    events = ()
    if calendar_checked:
        source_start, source_end = _window(week, zone_name)
        events = tuple(reader.list_commitments(source_start, source_end, zone_name))
        for event in events:
            if _overlaps(booking.starts_at, booking.ends_at,
                         event.starts_at, event.ends_at):
                codes.append("BOOKING_CONFLICTS_WITH_GOOGLE")
    if decision == "KEEP" and not codes:
        raise ValueError("KEEP is only valid for an open booking conflict")

    replacement = None
    target = None
    occupied = ()
    target_events = ()
    task_snapshot = None
    if decision == "MOVE":
        assert starts_at is not None and ends_at is not None
        zone = ZoneInfo(zone_name)
        local_day = starts_at.astimezone(zone).date()
        target_week = local_day - timedelta(days=local_day.weekday())
        replacement = ConfirmedTimeBlock(
            week_start=target_week, task_id=booking.task_id,
            segment_id=booking.segment_id, work_type_id=booking.work_type_id,
            starts_at=starts_at, ends_at=ends_at,
            transferred_from=booking.transferred_from,
        )
        if (_utc(ends_at) - _utc(starts_at)
                != _utc(booking.ends_at) - _utc(booking.starts_at)):
            raise ValueError("replacement must preserve the booked duration")
        window_start, window_end = _window(target_week, zone_name)
        if not (_utc(window_start) <= _utc(starts_at)
                and _utc(ends_at) <= _utc(window_end)):
            raise ValueError("replacement must fit within one local ISO week")
        if _utc(starts_at) < datetime.now(timezone.utc):
            raise ValueError("replacement cannot be in the past")
        aggregate = uow.tasks.get_aggregate(booking.task_id)
        if aggregate is None or aggregate.task.status not in (
                TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            raise ValueError("only open tasks can be moved")
        work_type = aggregate.task.work_type_id
        if booking.segment_id is not None:
            segment = next((s for s in aggregate.segments if s.id == booking.segment_id), None)
            if segment is None or segment.status not in (
                    SegmentStatus.TODO, SegmentStatus.IN_PROGRESS):
                raise ValueError("booked segment is no longer open")
            work_type = aggregate.effective_segment_work_type(segment.id).work_type_id
        if work_type != booking.work_type_id:
            raise ValueError("booked task work type changed")
        if aggregate.task.due_at and _utc(ends_at) > _utc(aggregate.task.due_at):
            raise ValueError("replacement exceeds the task deadline")
        task_snapshot = {
            "status": aggregate.task.status.value,
            "work_type_id": str(work_type),
            "due_at": str(aggregate.task.due_at),
            "segments": [(str(s.id), s.status.value, str(s.work_type_id))
                         for s in aggregate.segments],
        }
        target = (source if target_week == week else
                  effective_week(uow, owner, target_week, zone_name))
        if not _covered(replacement, target):
            raise ValueError("replacement is not in compatible effective availability")
        _, _, _, bookings = _state(
            uow, owner, target_week, target_week + timedelta(days=7),
        )
        occupied = tuple(b for b in bookings if b.id != booking_id)
        if any(_overlaps(starts_at, ends_at, b.starts_at, b.ends_at)
               for b in occupied):
            raise ValueError("replacement overlaps an active local booking")
        target_events = (events if target_week == week else tuple(
            reader.list_commitments(window_start, window_end, zone_name)
        ))
        if any(_overlaps(starts_at, ends_at, e.starts_at, e.ends_at)
               for e in target_events):
            raise ValueError("replacement overlaps a Google Calendar event")

    snapshot = {
        "algorithm": "TP-022R/v1", "owner": owner, "week": week.isoformat(),
        "zone": zone_name, "booking": asdict(booking),
        "source_revision": source.revision_fingerprint,
        "decision": decision, "reason": reason,
        "starts_at": starts_at, "ends_at": ends_at,
        "issues": [asdict(v) for v in issues],
        "calendar": [(e.calendar_id, e.event_id, e.starts_at, e.ends_at)
                     for e in events],
        "target_revision": target.revision_fingerprint if target else None,
        "bookings": [asdict(b) for b in occupied],
        "target_calendar": [(e.calendar_id, e.event_id, e.starts_at, e.ends_at)
                            for e in target_events],
        "task": task_snapshot,
    }
    fingerprint = sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    consequences = {
        "CANCEL": ("Cancel the local booking only; leave the task untouched.",),
        "MOVE": ("Supersede the old booking and create a new local booking atomically.",
                 "Leave the task and Google Calendar unchanged."),
        "KEEP": ("Keep the confirmed booking and its open conflict visible.",),
    }[decision]
    return ResolutionPreview(booking, decision, fingerprint,
                             tuple(sorted(set(codes))), replacement,
                             calendar_checked, consequences)


def preview_resolution(
    uow: UnitOfWork, reader: CalendarReader, owner: str, week: date,
    booking_id: UUID, revision: int, decision: Decision, zone_name: str,
    reason: str, starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> ResolutionPreview:
    with uow:
        return _prepare(uow, reader, owner, week, booking_id, revision,
                        decision, zone_name, reason, starts_at, ends_at)


def confirm_resolution(
    uow: UnitOfWork, reader: CalendarReader, owner: str, week: date,
    booking_id: UUID, revision: int, decision: Decision, zone_name: str,
    reason: str, fingerprint: str, decision_id: UUID,
    starts_at: datetime | None = None, ends_at: datetime | None = None,
) -> tuple[ConfirmedTimeBlock, ConfirmedTimeBlock | None]:
    with uow:
        uow.lock_planning()
        previous = uow.history_read.get(decision_id)
        if previous is not None:
            payload = previous.payload
            if (previous.entity_type != "TIME_BLOCK" or previous.entity_id != booking_id
                    or payload.get("owner") != owner
                    or payload.get("fingerprint") != fingerprint
                    or payload.get("decision") != decision):
                raise StaleBookingResolution("decision ID was already used")
            original = uow.time_blocks.get(booking_id)
            new_id = payload.get("replacement_id")
            assert original is not None
            original = replace(original, status=payload["result_status"],
                               revision=payload["result_revision"])
            created = uow.time_blocks.get(UUID(new_id)) if new_id else None
            if created is not None:
                created = replace(created, status="CONFIRMED", revision=1)
            return original, created
        try:
            preview = _prepare(uow, reader, owner, week, booking_id, revision,
                               decision, zone_name, reason, starts_at, ends_at)
        except (ValueError, LookupError) as exc:
            raise StaleBookingResolution("constraints changed; request a new preview") from exc
        if fingerprint != preview.fingerprint:
            raise StaleBookingResolution("resolution preview is stale")
        status = {"CANCEL": "CANCELLED", "MOVE": "SUPERSEDED", "KEEP": "CONFIRMED"}[decision]
        uow.time_blocks.revise(preview.booking, status=status)
        new_booking = preview.replacement
        if new_booking is not None:
            uow.time_blocks.add(new_booking)
        now = datetime.now(timezone.utc)
        uow.history.append(HistoryEvent(
            id=decision_id, occurred_at=now, recorded_at=now,
            entity_type="TIME_BLOCK", entity_id=booking_id, task_id=None,
            event_type={"CANCEL": "BOOKING_CANCELLED", "MOVE": "BOOKING_MOVED",
                        "KEEP": "BOOKING_CONFLICT_RETAINED"}[decision],
            schema_version=1, source=HistorySource.USER,
            reason_code=None, correlation_id=decision_id, causation_id=None,
            payload={
                "owner": owner, "decision": decision, "reason": reason,
                "fingerprint": fingerprint, "old_revision": revision,
                "result_status": status, "result_revision": revision + 1,
                "old_start": preview.booking.starts_at.isoformat(),
                "old_end": preview.booking.ends_at.isoformat(),
                "replacement_id": str(new_booking.id) if new_booking else None,
                "new_start": starts_at.isoformat() if starts_at else None,
                "new_end": ends_at.isoformat() if ends_at else None,
                "conflicts": list(preview.conflict_codes),
            },
        ))
        uow.commit()
        return replace(preview.booking, status=status, revision=revision + 1), new_booking


def list_resolution_history(
    uow: UnitOfWork, owner: str, week: date, booking_id: UUID,
) -> tuple[HistoryEvent, ...]:
    with uow:
        block = uow.time_blocks.get(booking_id)
        if block is None or block.week_start != week:
            raise LookupError("local booking not found")
        return tuple(v for v in uow.history_read.list_all()
                     if v.entity_type == "TIME_BLOCK" and v.entity_id == booking_id
                     and v.payload.get("owner") == owner)
