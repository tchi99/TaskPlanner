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
from app.domain.schedule_scopes import ScopeAffiliation, effective_scope


@dataclass(frozen=True, slots=True)
class EffectiveBlock:
    id: str
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None
    mode: AvailabilityMode | None
    sources: tuple[str, ...]
    scope_id: UUID | None = None

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
    scope_ids: tuple[UUID, ...] = ()


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
    scope_id: UUID | None = None
    civil_date: date | None = None


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
    *, compatibility_id: UUID | None = None,
    affiliations: Sequence[ScopeAffiliation] = (),
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
                               f"EXCEPTION:{targets[(value.rule_id, value.original_local_date)].id}:removed",
                               value.scope_id or compatibility_id, value.original_local_date))
            continue
        spans.append(_Span(value.starts_at, value.ends_at, value.kind.value,
                           value.work_type_id, value.mode,
                           f"RULE:{value.rule_id}:{value.original_local_date.isoformat()}:v{value.revision}",
                           value.scope_id or compatibility_id, value.original_local_date))
    for value in manual:
        spans.append(_Span(_utc(value.starts_at), _utc(value.ends_at), "MANUAL",
                           value.work_type_id, None, f"MANUAL:{value.id}",
                           value.scope_id or compatibility_id, value.starts_at.date()))
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
        target = targets.get((value.rule_id, value.original_local_date))
        source_rule = next((r for r in rules if r.id == value.rule_id), None)
        source_scope = None
        if source_rule and value.original_local_date:
            found, _ = expand_rules((source_rule,), value.original_local_date,
                                     value.original_local_date + timedelta(days=1))
            if found:
                source_scope = found[0].scope_id
        # CANCEL/REPLACE scope is that of its source occurrence. A scoped
        # UNAVAILABLE exception is local; a legacy one remains GLOBAL.
        scope = (value.scope_id or source_scope or compatibility_id)
        if value.action is ExceptionAction.UNAVAILABLE and value.scope_id is None:
            scope = None
        spans.append(_Span(interval[0], interval[1], category,
                           value.work_type_id, value.mode, f"EXCEPTION:{value.id}:v{value.version}",
                           scope, value.original_local_date or
                           value.starts_at.astimezone(ZoneInfo(value.timezone_name)).date()))
    spans = [_Span(max(v.start, lo), min(v.end, hi), v.bucket,
                   v.work_type, v.mode, v.source, v.scope_id, v.civil_date)
             for v in spans if v.start < hi and v.end > lo]
    points = sorted({lo, hi} | {v.start for v in spans} | {v.end for v in spans})
    blocks: list[EffectiveBlock] = []
    issues: list[EffectiveIssue] = []
    for start, end in zip(points, points[1:]):
        covered = [item for item in spans if item.start < end and item.end > start]
        if not covered:
            continue
        global_unavailable = [item for item in covered
                              if item.bucket == "UNAVAILABLE" and item.scope_id is None]
        if global_unavailable:
            issues.append(EffectiveIssue("DECLARED_UNAVAILABLE", start, end,
                                         tuple(item.source for item in global_unavailable)))
            continue
        scopes = sorted({item.scope_id for item in covered
                         if item.bucket != "UNAVAILABLE"}, key=str)
        candidates = []
        for scope in scopes:
            inside = [item for item in covered if item.scope_id == scope]
            blocked = [item for item in inside if item.bucket == "UNAVAILABLE"]
            if blocked:
                issues.append(EffectiveIssue("DECLARED_UNAVAILABLE", start, end,
                                             tuple(item.source for item in blocked),
                                             scope_ids=(scope,) if scope else ()))
                continue
            envelope = (any(item.bucket == "GENERAL" for item in inside)
                        and not any(item.bucket == "REMOVED" for item in inside))
            manual_cover = [item for item in inside if item.bucket == "MANUAL"]
            classified = [item for item in inside if item.bucket == "CATEGORIZED"]
            sources = tuple(sorted({item.source for item in inside}))
            if classified and not envelope:
                issues.append(EffectiveIssue("OUTSIDE_GENERAL_ENVELOPE", start, end,
                                             sources, scope_ids=(scope,) if scope else ()))
                if not manual_cover:
                    continue
            claims = manual_cover + classified
            categories = {item.work_type for item in claims}
            if len(categories) > 1:
                issues.append(EffectiveIssue("INCOMPATIBLE_WORK_TYPES", start, end,
                                             sources, scope_ids=(scope,) if scope else ()))
                continue
            if claims:
                chosen = claims[0].work_type
                modes = {item.mode for item in classified}
                if not manual_cover and len(modes) > 1:
                    issues.append(EffectiveIssue("INCOMPATIBLE_MODES", start, end,
                                                 sources, scope_ids=(scope,) if scope else ()))
                    continue
                mode = None if manual_cover else next(iter(modes))
                # An explicitly scoped declaration must match the dated leaf
                # affiliation; a legacy rule stays in compatibility until
                # explicitly migrated, not silently reinterpreted by its name.
                if (compatibility_id is not None and chosen is not None
                        and effective_scope(chosen, claims[0].civil_date or from_date,
                                            tuple(affiliations), compatibility_id) != scope):
                    issues.append(EffectiveIssue("AFFILIATION_SCOPE_MISMATCH", start, end,
                                                 sources, scope_ids=(scope,)))
                    continue
            elif envelope:
                chosen, mode = None, None
            else:
                continue
            candidates.append((scope, chosen, mode, sources))
        if len(candidates) > 1:
            all_sources = tuple(sorted({source for _, _, _, group in candidates
                                        for source in group}))
            issues.append(EffectiveIssue("INCOMPATIBLE_SCOPES", start, end,
                                         all_sources,
                                         scope_ids=tuple(scope for scope, *_ in candidates
                                                         if scope is not None)))
            continue
        if candidates:
            scope, chosen, mode, sources = candidates[0]
            identity = sha256(f"{start.isoformat()}|{end.isoformat()}|{scope}|{chosen}|{mode}|{sources}".encode()).hexdigest()[:24]
            blocks.append(EffectiveBlock(identity, start, end, chosen,
                                         mode, sources, scope))

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
            (v for v in blocks if (
                (v.work_type_id == booking.work_type_id
                 and (booking.scope_id is None or v.scope_id == booking.scope_id))
                or (booking.transferred_from is not None
                    and v.work_type_id == booking.transferred_from
                    and v.mode is AvailabilityMode.PREFERRED
                    and (booking.scope_id is None or v.scope_id == booking.scope_id))
             ) and v.starts_at < end and v.ends_at > start),
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
                and merged[-1].scope_id == block.scope_id
                and merged[-1].work_type_id == block.work_type_id
                and merged[-1].mode == block.mode
                and merged[-1].sources == block.sources):
            previous = merged.pop()
            identity = sha256(f"{previous.starts_at}|{block.ends_at}|{block.sources}".encode()).hexdigest()[:24]
            merged.append(EffectiveBlock(identity, previous.starts_at, block.ends_at,
                                         block.work_type_id, block.mode, block.sources,
                                         block.scope_id))
        else:
            merged.append(block)
    return EffectiveProjection(tuple(merged), tuple(issues), expansion,
                               sum(value.minutes for value in merged))
