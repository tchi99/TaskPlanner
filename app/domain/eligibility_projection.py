"""TP-025A: read-only physical timeline with alternative eligibility choices.

This adapter consumes the authoritative legacy physical projection; it does
not expose shared blocks to the legacy planner until TP-025B. Declared time
must never be presented as Google-verified free time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.effective_availability import EffectiveProjection, EffectiveIssue
from app.domain.eligibility import (
    EligibilitySeries, EligibilityException, EligibilityExpansionIssue,
    expand_eligibility,
)
from app.domain.recurring_availability import AvailabilityMode
from app.domain.schedule_scopes import ScopeAffiliation, effective_scope


@dataclass(frozen=True, slots=True)
class EligibilityChoice:
    work_type_id: UUID
    priority_rank: int | None
    sources: tuple[str, ...]
    exclusive: bool = False
    legacy_mode: AvailabilityMode | None = None


@dataclass(frozen=True, slots=True)
class PhysicalEligibilityFragment:
    starts_at: datetime
    ends_at: datetime
    scope_id: UUID | None
    sources: tuple[str, ...]
    choices: tuple[EligibilityChoice, ...]
    null_residual: bool
    verification: str = "DECLARED_ONLY"

    @property
    def minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)


@dataclass(frozen=True, slots=True)
class EligibilityProjection:
    fragments: tuple[PhysicalEligibilityFragment, ...]
    issues: tuple[EffectiveIssue, ...]
    expansion_issues: tuple[EligibilityExpansionIssue, ...]
    physical_minutes: int
    # Per-activity potentials are alternatives, NOT additive capacity.
    potential_minutes: tuple[tuple[UUID, int], ...]


def project_eligibility(
    physical: EffectiveProjection,
    series: tuple[EligibilitySeries, ...],
    exceptions: tuple[EligibilityException, ...],
    from_date: date,
    to_date: date,
    timezone_name: str,
    *,
    compatibility_id: UUID,
    affiliations: tuple[ScopeAffiliation, ...] = (),
) -> EligibilityProjection:
    """Partition one UTC physical timeline; retain legacy exclusivity.

    The physical projection includes parent GENERAL envelopes, historical
    CATEGORIZED/MANUAL claims, scoped UNAVAILABLE and historical exceptions.
    New permissions may only occupy residual NULL minutes *within* its parent.
    """
    zone = ZoneInfo(timezone_name)
    lo = datetime.combine(from_date, time.min, zone).astimezone(timezone.utc)
    hi = datetime.combine(to_date, time.min, zone).astimezone(timezone.utc)
    occurrences, expansion = expand_eligibility(series, exceptions, from_date, to_date)
    occurrences = tuple(item for item in occurrences
                        if item.starts_at < hi and item.ends_at > lo)
    # Dated leaf affiliations can change at a local midnight within a
    # permission or a moved occurrence. Split there before checking scope.
    local_midnights = set()
    for item in occurrences:
        local_zone = ZoneInfo(item.timezone_name)
        day = item.starts_at.astimezone(local_zone).date()
        last = item.ends_at.astimezone(local_zone).date()
        while day <= last:
            instant = datetime.combine(day, time.min, local_zone).astimezone(timezone.utc)
            if lo < instant < hi:
                local_midnights.add(instant)
            day += timedelta(days=1)
    boundaries = sorted({lo, hi} | local_midnights |
                        {edge for block in physical.blocks
                         for edge in (block.starts_at, block.ends_at)} |
                        {max(lo, item.starts_at) for item in occurrences} |
                        {min(hi, item.ends_at) for item in occurrences})
    fragments: list[PhysicalEligibilityFragment] = []
    issues = list(physical.issues)
    totals: dict[UUID, int] = {}
    for start, end in zip(boundaries, boundaries[1:]):
        if start >= end:
            continue
        base = next((block for block in physical.blocks
                     if block.starts_at <= start and block.ends_at >= end), None)
        touching = [item for item in occurrences
                    if item.starts_at < end and item.ends_at > start]
        if base is None:
            if touching:
                issues.append(EffectiveIssue(
                    "ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE", start, end,
                    tuple(sorted(item.source for item in touching)),
                    scope_ids=tuple(sorted({item.scope_id for item in touching}, key=str))))
            continue
        selections: list[EligibilityChoice] = []
        # A manual declaration is strict even when its work_type_id is NULL.
        # It cannot silently become a shared eligibility envelope.
        manual_strict = any(source.startswith("MANUAL:") for source in base.sources)
        if base.work_type_id is not None or manual_strict:
            if base.work_type_id is not None:
                selections.append(EligibilityChoice(
                    base.work_type_id, None, base.sources, True, base.mode))
            if touching:
                issues.append(EffectiveIssue(
                    "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE", start, end,
                    tuple(sorted(set(base.sources) | {item.source for item in touching})),
                    scope_ids=(base.scope_id,) if base.scope_id else ()))
        else:
            valid = []
            for item in touching:
                if item.scope_id != base.scope_id:
                    issues.append(EffectiveIssue(
                        "ELIGIBILITY_SCOPE_MISMATCH", start, end, (item.source,),
                        scope_ids=tuple(v for v in (base.scope_id, item.scope_id) if v)))
                    continue
                if effective_scope(item.work_type_id,
                                   start.astimezone(ZoneInfo(item.timezone_name)).date(),
                                   affiliations, compatibility_id) != item.scope_id:
                    issues.append(EffectiveIssue(
                        "ELIGIBILITY_AFFILIATION_MISMATCH", start, end, (item.source,),
                        scope_ids=(item.scope_id,)))
                    continue
                valid.append(item)
            for work_type in sorted({item.work_type_id for item in valid}, key=str):
                same = [item for item in valid if item.work_type_id == work_type]
                ranks = {item.priority_rank for item in same}
                sources = tuple(sorted({item.source for item in same}))
                if len(ranks) != 1:
                    issues.append(EffectiveIssue(
                        "CONFLICTING_ELIGIBILITY_RANKS", start, end, sources,
                        scope_ids=(base.scope_id,) if base.scope_id else ()))
                    continue  # Never choose a winner by UUID or insertion order.
                selections.append(EligibilityChoice(
                    work_type, same[0].priority_rank, sources))
        choices = tuple(sorted(selections, key=lambda value: str(value.work_type_id)))
        minutes = int((end - start).total_seconds() // 60)
        for choice in choices:
            totals[choice.work_type_id] = totals.get(choice.work_type_id, 0) + minutes
        fragments.append(PhysicalEligibilityFragment(
            start, end, base.scope_id, base.sources, choices,
            base.work_type_id is None and not manual_strict and not choices))
    # A fragment is a physical minute once, even when it carries N choices.
    assert sum(item.minutes for item in fragments) == physical.declared_minutes
    return EligibilityProjection(
        tuple(fragments), tuple(issues), expansion, physical.declared_minutes,
        tuple(sorted(totals.items(), key=lambda item: str(item[0]))),
    )
