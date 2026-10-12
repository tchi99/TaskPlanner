"""Deterministic, disjoint *declared* availability. No Google-free-time assertion.

TP-022C will connect consumers and external calendar verification. This module
only projects declarations and reports existing local reservation conflicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.capacity import AvailabilityBlock
from app.domain.recurring_availability import (
    AvailabilityMode, ExpansionIssue, RecurringAvailabilityRule, RuleKind, expand_rules,
)
from app.domain.time_blocks import ConfirmedTimeBlock


@dataclass(frozen=True, slots=True)
class EffectiveBlock:
    id: str
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None
    mode: AvailabilityMode | None
    sources: tuple[str, ...]

    @property
    def minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


@dataclass(frozen=True, slots=True)
class EffectiveIssue:
    code: str
    starts_at: datetime
    ends_at: datetime
    sources: tuple[str, ...]
    booking_id: UUID | None = None
    state: str = "OPEN"


@dataclass(frozen=True, slots=True)
class EffectiveProjection:
    blocks: tuple[EffectiveBlock, ...]
    issues: tuple[EffectiveIssue, ...]
    expansion_issues: tuple[ExpansionIssue, ...]
    declared_minutes: int


@dataclass(frozen=True, slots=True)
class _Span:
    start: datetime
    end: datetime
    bucket: str
    work_type: UUID | None
    mode: AvailabilityMode | None
    source: str


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def project_effective(
    rules: Sequence[RecurringAvailabilityRule],
    exceptions: Sequence[AvailabilityException],
    manual: Sequence[AvailabilityBlock],
    confirmed: Sequence[ConfirmedTimeBlock],
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> EffectiveProjection:
    """Half-open local dates. UTC partition ensures no interval counts twice."""
    days = (to_date - from_date).days
    if not 0 < days <= 93:
        raise ValueError("projection requires 1 to 93 days")
    zone = ZoneInfo(timezone_name)
    lo = datetime.combine(from_date, time.min, zone).astimezone(timezone.utc)
    hi = datetime.combine(to_date, time.min, zone).astimezone(timezone.utc)
    active = [value for value in exceptions if value.enabled]
    targets = {(e.rule_id, e.original_local_date): e for e in active
               if e.action in (ExceptionAction.CANCEL, ExceptionAction.REPLACE)}
    # A moved occurrence from another week is inserted independently below.
    occurrences, expansion = expand_rules(tuple(rules), from_date, to_date)
    spans: list[_Span] = []
    for value in occurrences:
        if (value.rule_id, value.original_local_date) in targets:
            # Cancelling or moving a categorized interval does NOT replenish
            # its minutes in the general NULL bucket.
            spans.append(_Span(value.starts_at, value.ends_at, "REMOVED", None, None,
                               f"EXCEPTION:{targets[(value.rule_id, value.original_local_date)].id}:removed"))
            continue
        spans.append(_Span(value.starts_at, value.ends_at, value.kind.value,
                           value.work_type_id, value.mode,
                           f"RULE:{value.rule_id}:{value.original_local_date.isoformat()}:v{value.revision}"))
    for value in manual:
        spans.append(_Span(_utc(value.starts_at), _utc(value.ends_at), "MANUAL",
                           value.work_type_id, None, f"MANUAL:{value.id}"))
    for value in active:
        if value.action is ExceptionAction.CANCEL:
            continue
        if value.action is ExceptionAction.REPLACE:
            source = next((r for r in rules if r.id == value.rule_id), None)
            if source is None or not expand_rules(
                    (source,), value.original_local_date,
                    value.original_local_date + timedelta(days=1))[0]:
                continue  # Orphaned replacement cannot become an implicit addition.
        interval = value.active_interval()
        assert interval is not None
        category = ("UNAVAILABLE" if value.action is ExceptionAction.UNAVAILABLE
                    else value.kind.value)
        spans.append(_Span(interval[0], interval[1], category,
                           value.work_type_id, value.mode, f"EXCEPTION:{value.id}:v{value.version}"))
    spans = [_Span(max(v.start, lo), min(v.end, hi), v.bucket,
                   v.work_type, v.mode, v.source) for v in spans if v.start < hi and v.end > lo]
    points = sorted({lo, hi} | {v.start for v in spans} | {v.end for v in spans})
    blocks: list[EffectiveBlock] = []
    issues: list[EffectiveIssue] = []
    for start, end in zip(points, points[1:]):
        covered = [v for v in spans if v.start < end and v.end > start]
        if not covered:
            continue
        sources = tuple(sorted({v.source for v in covered}))
        unavailable = [v for v in covered if v.bucket == "UNAVAILABLE"]
        if unavailable:
            issues.append(EffectiveIssue("DECLARED_UNAVAILABLE", start, end,
                                         tuple(v.source for v in unavailable)))
            continue
        envelope = (any(v.bucket == "GENERAL" for v in covered)
                    and not any(v.bucket == "REMOVED" for v in covered))
        manual_cover = [v for v in covered if v.bucket == "MANUAL"]
        classified = [v for v in covered if v.bucket == "CATEGORIZED"]
        if classified and not envelope:
            issues.append(EffectiveIssue("OUTSIDE_GENERAL_ENVELOPE", start, end, sources))
            # A legacy explicit block remains valid without a recurring envelope,
            # unless the recurring declaration disagrees about the category.
            if not manual_cover:
                continue
        claims = manual_cover + classified
        categories = {v.work_type for v in claims}
        if len(categories) > 1:
            issues.append(EffectiveIssue("INCOMPATIBLE_WORK_TYPES", start, end, sources))
            continue
        if claims:
            # Manual declarations retain strict legacy semantics (mode=None).
            manual_mode = bool(manual_cover)
            selected_type = claims[0].work_type
            modes = {v.mode for v in classified}
            if not manual_mode and len(modes) > 1:
                issues.append(EffectiveIssue("INCOMPATIBLE_MODES", start, end, sources))
                continue
            selected_mode = None if manual_mode else next(iter(modes))
        elif envelope:
            selected_type, selected_mode = None, None
        else:
            continue
        identity = sha256(f"{start.isoformat()}|{end.isoformat()}|{selected_type}|{selected_mode}|{sources}".encode()).hexdigest()[:24]
        blocks.append(EffectiveBlock(identity, start, end, selected_type,
                                     selected_mode, sources))

    # A rule revision may make a future exception's origin disappear. Retain
    # the data and surface the orphan; never reinterpret it as an implicit ADD.
    for exc in active:
        if exc.rule_id is None or exc.original_local_date is None:
            continue
        origin = exc.original_local_date
        rule = next((v for v in rules if v.id == exc.rule_id), None)
        valid = False
        if rule is not None:
            found, _ = expand_rules((rule,), origin, origin + timedelta(days=1))
            valid = bool(found)
        if not valid:
            if (from_date <= origin < to_date or
                    (exc.active_interval() is not None and
                     exc.active_interval()[0] < hi and exc.active_interval()[1] > lo)):
                issues.append(EffectiveIssue("ORPHANED_EXCEPTION", lo, hi,
                                             (f"EXCEPTION:{exc.id}",)))
            # Orphaned replacements were excluded from declaration spans above.
    for booking in confirmed:
        start, end = _utc(booking.starts_at), _utc(booking.ends_at)
        if start >= hi or end <= lo:
            continue
        start, end = max(start, lo), min(end, hi)
        matching = sorted(
            (v for v in blocks if v.work_type_id == booking.work_type_id
             and v.starts_at < end and v.ends_at > start),
            key=lambda v: v.starts_at,
        )
        cursor = start
        for segment in matching:
            if segment.starts_at > cursor:
                break
            cursor = max(cursor, segment.ends_at)
            if cursor >= end:
                break
        if cursor < end:
            issues.append(EffectiveIssue(
                "BOOKING_OUTSIDE_EFFECTIVE_AVAILABILITY", start, end,
                (f"BOOKING:{booking.id}",), booking.id,
            ))
    # Coalesce fragments with identical classification and provenance.
    merged: list[EffectiveBlock] = []
    for block in blocks:
        if (merged and merged[-1].ends_at == block.starts_at
                and merged[-1].work_type_id == block.work_type_id
                and merged[-1].mode == block.mode
                and merged[-1].sources == block.sources):
            previous = merged.pop()
            identity = sha256(f"{previous.starts_at}|{block.ends_at}|{block.sources}".encode()).hexdigest()[:24]
            merged.append(EffectiveBlock(identity, previous.starts_at, block.ends_at,
                                         block.work_type_id, block.mode, block.sources))
        else:
            merged.append(block)
    return EffectiveProjection(tuple(merged), tuple(issues), expansion,
                               sum(value.minutes for value in merged))
