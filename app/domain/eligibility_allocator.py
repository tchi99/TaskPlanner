"""TP-025B: one physical minute, several possible work types.

Allocation is a deterministic proposal, never a booking. A priority is local
to a physical fragment and cannot reserve otherwise free time invisibly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import ceil, floor
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.calendar import CalendarCommitment
from app.domain.eligibility_projection import EligibilityChoice, EligibilityProjection
from app.domain.model import ProtectionLevel, SegmentStatus, TaskStatus
from app.domain.recurring_availability import AvailabilityMode
from app.domain.task_rules import TaskAggregate
from app.domain.time_blocks import (
    ConfirmedTimeBlock, SuggestedTimeBlock, TimeBlockPreview, UnplacedWork,
)


@dataclass(frozen=True, slots=True)
class FixedTimeRequest:
    task_id: UUID
    starts_at: datetime
    ends_at: datetime
    segment_id: UUID | None = None

    def __post_init__(self):
        if (self.starts_at.tzinfo is None or self.ends_at.tzinfo is None
                or self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None):
            raise ValueError("fixed times must be offset-aware")
        if any(v.second or v.microsecond for v in (self.starts_at, self.ends_at)):
            raise ValueError("fixed times must be minute-aligned")
        if self.ends_at.astimezone(timezone.utc) <= self.starts_at.astimezone(timezone.utc):
            raise ValueError("fixed interval must have positive duration")


def _minute(value: datetime) -> int:
    return int(value.astimezone(timezone.utc).timestamp() // 60)


def suggest_eligible_blocks(
    week_start: date,
    timezone_name: str,
    projection: EligibilityProjection,
    commitments: Sequence[CalendarCommitment],
    confirmed: Sequence[ConfirmedTimeBlock],
    candidates: Sequence[TaskAggregate],
    *,
    availability_fingerprint: str,
    fixed: Sequence[FixedTimeRequest] = (),
    offer_transfers: bool = False,
    work_type_scopes: dict[UUID, UUID] | None = None,
) -> TimeBlockPreview:
    """Allocate shared/free physical minutes once using the accepted ADR order.

    Required constraints are checked first; candidates competing for each
    remaining minute are ranked by effective protection, fragment-local rank,
    due date, user order and stable segment ID. The greedy method does not
    assert mathematical infeasibility when work remains unplaced.
    """
    zone = ZoneInfo(timezone_name)
    week_end = week_start.fromordinal(week_start.toordinal() + 7)
    from datetime import time
    low = _minute(datetime.combine(week_start, time.min, zone))
    high = _minute(datetime.combine(week_end, time.min, zone))
    if not candidates or len({v.task.id for v in candidates}) != len(candidates):
        raise ValueError("candidate tasks must be nonempty and unique")
    if any(v.week_start != week_start for v in confirmed):
        raise ValueError("confirmed booking belongs to another week")
    # Every key is ONE physical minute. A shared permission adds choices, not keys.
    eligible: dict[int, tuple[UUID | None, tuple]] = {}
    # Unclassified NULL capacity is not a cross-parent commons: only an
    # unambiguous one-parent week can admit an unclassified work unit.
    scopes = {fragment.scope_id for fragment in projection.fragments}
    for fragment in projection.fragments:
        for minute in range(max(low, _minute(fragment.starts_at)),
                            min(high, _minute(fragment.ends_at))):
            if minute in eligible:
                raise ValueError("physical projection overlaps itself")
            if fragment.choices:
                eligible[minute] = (fragment.scope_id, fragment.choices)
            elif fragment.null_residual and len(scopes) == 1:
                eligible[minute] = (fragment.scope_id, (
                    EligibilityChoice(None, None, fragment.sources, exclusive=True),
                ))
    busy_ranges = [
        (floor(v.starts_at.astimezone(timezone.utc).timestamp() / 60),
         ceil(v.ends_at.astimezone(timezone.utc).timestamp() / 60))
        for v in commitments
    ]
    busy_ranges += [(_minute(v.starts_at), _minute(v.ends_at)) for v in confirmed]
    occupied = {m for a, b in busy_ranges
                for m in range(max(low, a), min(high, b))}
    free = set(eligible) - occupied
    already = {v.task_id for v in confirmed}
    units = []
    snapshot_tasks = []
    for order, aggregate in enumerate(candidates):
        task = aggregate.task
        if task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            raise ValueError("only open clarified tasks may be planned")
        opened = sorted((s for s in aggregate.segments if s.status in
                         (SegmentStatus.TODO, SegmentStatus.IN_PROGRESS)),
                        key=lambda s: (s.position, str(s.id)))
        if opened:
            parts = [(s.id, s.title,
                      aggregate.effective_segment_work_type(s.id).work_type_id,
                      s.estimated_minutes,
                      aggregate.effective_segment_protection(s.id))
                     for s in opened]
        elif not aggregate.segments:
            parts = [(None, task.title, task.work_type_id,
                      task.estimated_minutes, task.protection)]
        else:
            parts = []
        task_detail = [str(task.id), task.status.value, task.protection.value,
                       str(task.work_type_id), task.estimated_minutes,
                       task.due_at.isoformat() if task.due_at else None, []]
        for position, (segment, label, work_type, estimate, protection) in enumerate(parts):
            task_detail[-1].append([str(segment), label, str(work_type),
                                    estimate, protection.value, position])
            units.append({
                "task": task.id, "segment": segment, "label": label,
                "type": work_type, "estimate": estimate, "remaining": estimate,
                "protection": protection, "due": (_minute(task.due_at)
                                                    if task.due_at else high),
                "order": order, "position": position,
                "blocked": ("ALREADY_CONFIRMED" if task.id in already else
                            "ESTIMATE_UNKNOWN" if estimate is None else None),
            })
        snapshot_tasks.append(task_detail)
    identifiers = {(unit["task"], unit["segment"]): unit for unit in units}
    if len({(v.task_id, v.segment_id) for v in fixed}) != len(fixed):
        raise ValueError("duplicate fixed work unit")
    assignments: dict[int, tuple[dict, UUID | None, tuple[str, ...], int | None, str, UUID | None]] = {}
    problems: dict[tuple[UUID, UUID | None], str] = {}
    # Fixed meetings are indivisible: a partial free span is never accepted.
    for request in fixed:
        key = (request.task_id, request.segment_id)
        unit = identifiers.get(key)
        if unit is None:
            raise ValueError("fixed request must name one open selected work unit")
        if unit["blocked"]:
            problems[key] = unit["blocked"]
            continue
        start, end = _minute(request.starts_at), _minute(request.ends_at)
        if (start < low or end > high or end - start != unit["remaining"]
                or end > unit["due"]):
            problems[key] = "FIXED_DURATION_OR_WINDOW_INVALID"
            continue
        matching = []
        for minute in range(start, end):
            scope_choices = eligible.get(minute)
            matches = [] if scope_choices is None else [
                v for v in scope_choices[1] if v.work_type_id == unit["type"]]
            if minute not in free or not matches:
                break
            matching.append((scope_choices[0], matches[0]))
        if len(matching) != end - start or len({s for s, _ in matching}) != 1:
            problems[key] = "FIXED_SLOT_NOT_VERIFIED_FREE_OR_ADMISSIBLE"
            continue
        sources = tuple(sorted({src for _, choice in matching for src in choice.sources}))
        for minute in range(start, end):
            assignments[minute] = (unit, matching[0][0], sources,
                                   None, "FIXED_ELIGIBLE", None)
        free.difference_update(range(start, end))
        unit["remaining"] = 0
    protection = {ProtectionLevel.PROTECTED: 0,
                  ProtectionLevel.REPLANNABLE: 1,
                  ProtectionLevel.FLEXIBLE: 2}
    fixed_keys = {(v.task_id, v.segment_id) for v in fixed}
    # A later segment may not leapfrog an unfinished earlier segment.
    def ready(unit):
        return all(other["remaining"] == 0 or other["blocked"] is not None
                   for other in units
                   if other["task"] == unit["task"]
                   and other["position"] < unit["position"])

    for minute in sorted(free):
        scope, choices = eligible[minute]
        competitors = []
        for unit in units:
            if unit["blocked"] or (unit["task"], unit["segment"]) in fixed_keys:
                continue
            if not unit["remaining"] or minute >= unit["due"] or not ready(unit):
                continue
            for choice in choices:
                if choice.work_type_id == unit["type"]:
                    competitors.append(((
                        protection[unit["protection"]],
                        choice.priority_rank if choice.priority_rank is not None else 10**9,
                        unit["due"], unit["order"], unit["position"],
                        str(unit["task"]), str(unit["segment"])),
                        unit, choice))
                    break
        if not competitors:
            continue
        _, winner, choice = min(competitors, key=lambda entry: entry[0])
        assignments[minute] = (winner, scope, choice.sources, choice.priority_rank,
                               "CONTEXTUAL_PRIORITY" if choice.priority_rank is not None
                               else "ADMISSIBLE_FREE", None)
        winner["remaining"] -= 1
    # An exclusive legacy PREFERRED declaration can still be offered as a
    # transfer, but it is never silently accepted and never crosses parents.
    if offer_transfers:
        unused = set(eligible) - occupied - set(assignments)
        for unit in units:
            if unit["blocked"] or not unit["remaining"] or unit["type"] is None:
                continue
            if (unit["task"], unit["segment"]) in fixed_keys:
                continue
            target_scope = (work_type_scopes or {}).get(unit["type"])
            for minute in sorted(unused):
                if not unit["remaining"]:
                    break
                if minute >= unit["due"]:
                    continue
                scope, choices = eligible[minute]
                donors = [choice for choice in choices
                          if choice.exclusive
                          and choice.legacy_mode is AvailabilityMode.PREFERRED
                          and choice.work_type_id != unit["type"]
                          and target_scope is not None and scope == target_scope]
                if not donors:
                    continue
                donor = donors[0]
                assignments[minute] = (
                    unit, scope, donor.sources, None, "PREFERRED_TRANSFER",
                    donor.work_type_id)
                unused.remove(minute)
                unit["remaining"] -= 1
    # Group consecutive allocations with the same unit and provenance.
    suggestions = []
    sequence = sorted(assignments)
    for minute in sequence:
        unit, scope, sources, rank, reason, donor = assignments[minute]
        if suggestions and minute == _minute(suggestions[-1].ends_at) and (
            suggestions[-1].task_id == unit["task"]
            and suggestions[-1].segment_id == unit["segment"]
            and suggestions[-1].scope_id == scope
            and suggestions[-1].eligibility_sources == sources
            and suggestions[-1].priority_rank == rank
            and suggestions[-1].placement_reason == reason
            and suggestions[-1].transferred_from == donor
        ):
            from dataclasses import replace
            last = suggestions[-1]
            suggestions[-1] = replace(
                last, ends_at=datetime.fromtimestamp((minute + 1) * 60, timezone.utc).astimezone(zone),
                minutes=last.minutes + 1)
        else:
            suggestions.append(SuggestedTimeBlock(
                task_id=unit["task"], segment_id=unit["segment"], label=unit["label"],
                work_type_id=unit["type"],
                starts_at=datetime.fromtimestamp(minute * 60, timezone.utc).astimezone(zone),
                ends_at=datetime.fromtimestamp((minute + 1) * 60, timezone.utc).astimezone(zone),
                minutes=1, transferred_from=donor, scope_id=scope,
                eligibility_sources=sources, priority_rank=rank, placement_reason=reason))
    unplaced = tuple(UnplacedWork(
        unit["task"], unit["segment"], unit["label"],
        unit["remaining"], problems.get((unit["task"], unit["segment"]))
        or unit["blocked"] or "NO_PLACEMENT_FOUND_BY_GREEDY_STRATEGY")
        for unit in units if unit["remaining"] is None or unit["remaining"] > 0)
    snapshot = {
        "algorithm": "TP-025B/contextual-v1", "week": week_start.isoformat(),
        "timezone": timezone_name, "availability_revision": availability_fingerprint,
        "tasks": snapshot_tasks, "offer_transfers": offer_transfers,
        "fixed": [(str(v.task_id), str(v.segment_id), v.starts_at.isoformat(),
                   v.ends_at.isoformat()) for v in fixed],
        "calendar": sorted((v.calendar_id, v.event_id, v.starts_at.isoformat(),
                            v.ends_at.isoformat()) for v in commitments),
        "confirmed": sorted((str(v.id), str(v.task_id), str(v.segment_id),
                             v.starts_at.isoformat(), v.ends_at.isoformat(),
                             v.revision) for v in confirmed),
        "placements": [(str(v.task_id), str(v.segment_id), v.starts_at.isoformat(),
                        v.ends_at.isoformat(), v.placement_reason, v.eligibility_sources)
                       for v in suggestions],
    }
    fingerprint = sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return TimeBlockPreview(
        week_start, timezone_name, tuple(v.task.id for v in candidates),
        fingerprint, tuple(suggestions), unplaced,
        bool(suggestions) and not unplaced,
        any(v.transferred_from is not None for v in suggestions),
    )
