"""TP-041: deterministic time-block suggestions, never calendar writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import ceil, floor
from typing import Sequence
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.domain.calendar import CalendarCommitment
from app.domain.capacity import AvailabilityBlock, validate_blocks
from app.domain.model import SegmentStatus, TaskStatus
from app.domain.task_rules import TaskAggregate


@dataclass(frozen=True, slots=True)
class ConfirmedTimeBlock:
    week_start: date
    task_id: UUID
    segment_id: UUID | None
    work_type_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    id: UUID = field(default_factory=uuid4)
    transferred_from: UUID | None = None

    def __post_init__(self) -> None:
        if any(v.tzinfo is None or v.utcoffset() is None
               for v in (self.starts_at, self.ends_at)):
            raise ValueError("time block timestamps must be timezone-aware")
        if self.ends_at.astimezone(timezone.utc) <= self.starts_at.astimezone(timezone.utc):
            raise ValueError("time block end must follow start")
        if any(v.second or v.microsecond for v in (self.starts_at, self.ends_at)):
            raise ValueError("time block timestamps must align to whole minutes")


@dataclass(frozen=True, slots=True)
class SuggestedTimeBlock:
    task_id: UUID
    segment_id: UUID | None
    label: str
    work_type_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    minutes: int
    transferred_from: UUID | None = None


@dataclass(frozen=True, slots=True)
class UnplacedWork:
    task_id: UUID
    segment_id: UUID | None
    label: str
    remaining_minutes: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class TimeBlockPreview:
    week_start: date
    timezone_name: str
    task_ids: tuple[UUID, ...]
    fingerprint: str
    suggestions: tuple[SuggestedTimeBlock, ...]
    unplaced: tuple[UnplacedWork, ...]
    can_confirm: bool
    requires_transfer_confirmation: bool = False


def _minute(dt: datetime, *, round_up: bool = False) -> int:
    seconds = dt.astimezone(timezone.utc).timestamp() / 60
    return ceil(seconds) if round_up else floor(seconds)


def _free_intervals(
    blocks: Sequence[AvailabilityBlock],
    events: Sequence[CalendarCommitment],
    confirmed: Sequence[ConfirmedTimeBlock],
) -> dict[UUID | None, list[list[int]]]:
    """Cut occupied intervals conservatively, using actual UTC instants."""
    busy = [(_minute(e.starts_at), _minute(e.ends_at, round_up=True))
            for e in events]
    busy.extend((_minute(b.starts_at), _minute(b.ends_at)) for b in confirmed)
    free: dict[UUID | None, list[list[int]]] = {}
    for block in blocks:
        lo, hi = _minute(block.starts_at), _minute(block.ends_at)
        cursor = lo
        for start, end in sorted((max(lo, a), min(hi, b))
                                 for a, b in busy if a < hi and b > lo):
            if start > cursor:
                free.setdefault(block.work_type_id, []).append([cursor, start])
            cursor = max(cursor, end)
        if cursor < hi:
            free.setdefault(block.work_type_id, []).append([cursor, hi])
    for intervals in free.values():
        intervals.sort()
    return free


def suggest_time_blocks(
    week_start: date,
    timezone_name: str,
    manual_blocks: Sequence[AvailabilityBlock],
    commitments: Sequence[CalendarCommitment],
    confirmed: Sequence[ConfirmedTimeBlock],
    candidates: Sequence[TaskAggregate],
    *, preferred_blocks: Sequence[AvailabilityBlock] = (),
    offer_transfers: bool = False,
    availability_fingerprint: str | None = None,
) -> TimeBlockPreview:
    """Greedily place user-ordered open work units inside genuinely free time.

    This does not reprioritize candidates, split task ownership, invent estimates
    or silently accept a partial schedule. A unit may use multiple free spans.
    """
    validate_blocks(week_start, manual_blocks)
    block_ids = {v.id for v in manual_blocks}
    if any(v.id not in block_ids for v in preferred_blocks):
        raise ValueError("preferred blocks must come from effective availability")
    zone = ZoneInfo(timezone_name)
    task_ids = [a.task.id for a in candidates]
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("candidate tasks must be nonempty and unique")
    for value in confirmed:
        if value.week_start != week_start:
            raise ValueError("confirmed block belongs to another week")
    free = _free_intervals(manual_blocks, commitments, confirmed)
    already_planned = {b.task_id for b in confirmed}
    suggestions: list[SuggestedTimeBlock] = []
    unplaced: list[UnplacedWork] = []
    pending: list[tuple[UUID, UUID | None, str, UUID | None, int, datetime | None]] = []
    units: list[tuple[UUID, UUID | None, str, UUID | None, int | None, datetime | None]] = []
    snapshot = {
        "week": week_start.isoformat(), "timezone": timezone_name,
        "availability_revision": availability_fingerprint,
        "offer_transfers": offer_transfers,
        "preferred": sorted(str(v.id) for v in preferred_blocks),
        "manual": sorted((str(b.id), b.starts_at.isoformat(), b.ends_at.isoformat(),
                          str(b.work_type_id)) for b in manual_blocks),
        "calendar": sorted((c.calendar_id, c.event_id, c.starts_at.isoformat(),
                            c.ends_at.isoformat()) for c in commitments),
        "confirmed": sorted((str(b.id), str(b.task_id), str(b.segment_id),
                             b.starts_at.isoformat(), b.ends_at.isoformat()) for b in confirmed),
        "tasks": [],
    }
    for aggregate in candidates:
        task = aggregate.task
        if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            raise ValueError("only open clarified tasks can be time-blocked")
        detail = [str(task.id), task.status.value, task.protection.value,
                  task.estimated_minutes, str(task.work_type_id),
                  task.due_at.isoformat() if task.due_at else None, []]
        snapshot["tasks"].append(detail)
        opened = sorted((s for s in aggregate.segments if s.status in
                         (SegmentStatus.TODO, SegmentStatus.IN_PROGRESS)),
                        key=lambda s: s.position)
        if opened:
            for s in opened:
                work_type = aggregate.effective_segment_work_type(s.id).work_type_id
                detail[6].append([str(s.id), s.status.value, s.estimated_minutes,
                                  str(work_type), str(s.protection_override), s.position])
                units.append((task.id, s.id, s.title, work_type,
                              s.estimated_minutes, task.due_at))
        elif not aggregate.segments:
            units.append((task.id, None, task.title, task.work_type_id,
                          task.estimated_minutes, task.due_at))
        else:
            detail[6].append(["all-segments-terminal"])
    for task_id, segment_id, label, work_type, estimate, due_at in units:
        if task_id in already_planned:
            unplaced.append(UnplacedWork(task_id, segment_id, label, estimate,
                                         "ALREADY_CONFIRMED"))
            continue
        if estimate is None:
            unplaced.append(UnplacedWork(task_id, segment_id, label, None,
                                         "ESTIMATE_UNKNOWN"))
            continue
        remaining = estimate
        windows = free.get(work_type, [])
        cutoff = _minute(due_at) if due_at is not None else None
        for interval in windows:
            if remaining == 0:
                break
            if cutoff is not None and interval[0] >= cutoff:
                continue
            end = min(interval[1], cutoff) if cutoff is not None else interval[1]
            length = min(remaining, max(0, end - interval[0]))
            if length <= 0:
                continue
            start = interval[0]
            interval[0] += length
            remaining -= length
            begins = datetime.fromtimestamp(start * 60, tz=timezone.utc).astimezone(zone)
            finishes = datetime.fromtimestamp((start + length) * 60, tz=timezone.utc).astimezone(zone)
            suggestions.append(SuggestedTimeBlock(
                task_id, segment_id, label, work_type, begins, finishes, length
            ))
        if remaining:
            pending.append((task_id, segment_id, label, work_type, remaining, due_at))
    # All strict allocations happen first; only unused PREFERRED minutes may
    # be offered to another WorkType. PROTECTED, manual and NULL are never donors.
    if offer_transfers and pending and preferred_blocks:
        tentative = tuple(ConfirmedTimeBlock(
            week_start, s.task_id, s.segment_id, s.work_type_id,
            s.starts_at, s.ends_at,
        ) for s in suggestions)
        transferable = _free_intervals(preferred_blocks, commitments,
                                       (*confirmed, *tentative))
        revised = []
        for task_id, segment_id, label, work_type, remaining, due_at in pending:
            cutoff = _minute(due_at) if due_at is not None else None
            for donor in sorted(transferable, key=lambda v: str(v)):
                if donor == work_type or donor is None:
                    continue
                for interval in transferable[donor]:
                    if not remaining:
                        break
                    if cutoff is not None and interval[0] >= cutoff:
                        continue
                    limit = min(interval[1], cutoff) if cutoff is not None else interval[1]
                    length = min(remaining, max(0, limit - interval[0]))
                    if not length:
                        continue
                    start = interval[0]
                    interval[0] += length
                    remaining -= length
                    begins = datetime.fromtimestamp(start * 60, tz=timezone.utc).astimezone(zone)
                    ends = datetime.fromtimestamp((start + length) * 60, tz=timezone.utc).astimezone(zone)
                    suggestions.append(SuggestedTimeBlock(
                        task_id, segment_id, label, work_type, begins, ends,
                        length, transferred_from=donor,
                    ))
                if not remaining:
                    break
            if remaining:
                revised.append((task_id, segment_id, label, work_type, remaining, due_at))
        pending = revised
    for task_id, segment_id, label, _, remaining, _ in pending:
        unplaced.append(UnplacedWork(task_id, segment_id, label, remaining,
                                     "INSUFFICIENT_FREE_TIME_BEFORE_DEADLINE"))
    fingerprint = sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return TimeBlockPreview(
        week_start, timezone_name, tuple(task_ids), fingerprint,
        tuple(suggestions), tuple(unplaced),
        bool(suggestions) and not unplaced,
        any(v.transferred_from is not None for v in suggestions),
    )
