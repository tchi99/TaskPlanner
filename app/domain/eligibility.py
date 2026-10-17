"""TP-025A: opt-in, versioned permissions, NOT capacity or reservations.

Legacy GENERAL/CATEGORIZED and their CANCEL/REPLACE exceptions retain their
historical semantics. These records are deliberately not consumed by the old
time-block allocator until TP-025B adapts its physical-capacity contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.recurring_availability import _instant, _wall_clock


class EligibilityConflict(Exception):
    """Optimistic concurrency error for a versioned permission or exception."""


class EligibilityAction(StrEnum):
    REMOVE = "REMOVE"
    MOVE = "MOVE"


@dataclass(frozen=True, slots=True)
class EligibilityRevision:
    series_id: UUID
    number: int
    effective_from: date
    valid_until: date | None
    timezone_name: str
    days_of_week: tuple[int, ...]
    starts_at_local: str
    ends_at_local: str
    priority_rank: int | None = None  # Lower number is preferred; None means neutral.
    enabled: bool = True
    start_fold: int | None = None
    end_fold: int | None = None
    supersedes_future: bool = False

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("eligibility revision number must be positive")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        if (not self.days_of_week or self.days_of_week != tuple(sorted(set(self.days_of_week)))
                or any(type(day) is not int or not 0 <= day <= 6 for day in self.days_of_week)):
            raise ValueError("days_of_week must be sorted unique values 0 to 6")
        if self.valid_until is not None and self.valid_until <= self.effective_from:
            raise ValueError("valid_until must follow effective_from")
        if _wall_clock(self.ends_at_local, end=True) <= _wall_clock(self.starts_at_local):
            raise ValueError("ends_at_local must follow starts_at_local")
        if self.priority_rank is not None and (
                type(self.priority_rank) is not int or self.priority_rank < 1):
            raise ValueError("priority_rank must be positive or neutral")
        if self.start_fold not in (None, 0, 1) or self.end_fold not in (None, 0, 1):
            raise ValueError("DST fold must be 0, 1 or omitted")


@dataclass(frozen=True, slots=True)
class EligibilitySeries:
    id: UUID
    owner_id: str
    scope_id: UUID
    work_type_id: UUID
    version: int
    revisions: tuple[EligibilityRevision, ...]

    def __post_init__(self) -> None:
        if not self.owner_id or len(self.owner_id) > 128 or not self.revisions:
            raise ValueError("eligibility series must have an owner and revisions")
        if self.version != len(self.revisions) or any(
                rev.series_id != self.id or rev.number != index
                for index, rev in enumerate(self.revisions, start=1)):
            raise ValueError("eligibility series revision mismatch")


@dataclass(frozen=True, slots=True)
class EligibilityException:
    id: UUID
    owner_id: str
    series_id: UUID
    original_local_date: date
    version: int
    action: EligibilityAction
    timezone_name: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.owner_id or len(self.owner_id) > 128 or self.version < 1:
            raise ValueError("invalid exception owner or version")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        if self.action is EligibilityAction.REMOVE:
            if self.starts_at is not None or self.ends_at is not None:
                raise ValueError("REMOVE must not supply a replacement")
        elif self.action is EligibilityAction.MOVE:
            if self.starts_at is None or self.ends_at is None:
                raise ValueError("MOVE requires both instants")
            for value in (self.starts_at, self.ends_at):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("MOVE instants require timezone offsets")
                if value.second or value.microsecond:
                    raise ValueError("MOVE instants must align to whole minutes")
            if not timedelta(0) < (
                    self.ends_at.astimezone(timezone.utc) -
                    self.starts_at.astimezone(timezone.utc)) <= timedelta(days=1):
                raise ValueError("MOVE must have positive duration at most one day")
        else:
            raise ValueError("unknown eligibility exception action")


@dataclass(frozen=True, slots=True)
class EligibilityOccurrence:
    series_id: UUID
    revision: int
    original_local_date: date
    starts_at: datetime  # UTC
    ends_at: datetime    # UTC
    scope_id: UUID
    work_type_id: UUID
    priority_rank: int | None
    source: str


@dataclass(frozen=True, slots=True)
class EligibilityExpansionIssue:
    code: str
    series_id: UUID
    original_local_date: date


def expand_eligibility(
    series: tuple[EligibilitySeries, ...],
    exceptions: tuple[EligibilityException, ...],
    from_date: date,
    to_date: date,
) -> tuple[tuple[EligibilityOccurrence, ...], tuple[EligibilityExpansionIssue, ...]]:
    """Expand 1..93 civil days with DST validation and permission-local exceptions.

    MOVE may bring an occurrence into this window from outside it. Exceptions
    with an absent origin stay visible as ORPHANED_ELIGIBILITY_EXCEPTION.
    No time, physical capacity, or other work type is added by REMOVE/MOVE.
    """
    days = (to_date - from_date).days
    if not 0 < days <= 93:
        raise ValueError("eligibility expansion requires 1 to 93 days")
    by_series = {item.id: item for item in series}
    targets: dict[tuple[UUID, date], EligibilityException] = {}
    issues: list[EligibilityExpansionIssue] = []
    for exc in exceptions:
        if not exc.enabled:
            continue
        key = (exc.series_id, exc.original_local_date)
        if key in targets:
            issues.append(EligibilityExpansionIssue(
                "DUPLICATE_ELIGIBILITY_EXCEPTION", exc.series_id, exc.original_local_date))
            continue
        targets[key] = exc

    def origin(rule: EligibilitySeries, day: date):
        revisions = [rev for rev in rule.revisions if rev.effective_from <= day]
        if not revisions or any(rev.supersedes_future for rev in revisions):
            return None
        rev = max(revisions, key=lambda value: (value.effective_from, value.number))
        if (not rev.enabled or day.weekday() not in rev.days_of_week
                or (rev.valid_until is not None and day >= rev.valid_until)):
            return None
        try:
            zone = ZoneInfo(rev.timezone_name)
            start = _instant(day, rev.starts_at_local, zone, rev.start_fold)
            end = _instant(day, rev.ends_at_local, zone, rev.end_fold)
            if end <= start:
                raise ValueError("NON_POSITIVE_UTC_DURATION")
        except ValueError as exc:
            issues.append(EligibilityExpansionIssue(str(exc), rule.id, day))
            return None
        return rev, start, end

    occurrences = []
    checked: set[tuple[UUID, date]] = set()
    for rule in series:
        dates = {from_date + timedelta(days=index) for index in range(days)}
        dates |= {exc.original_local_date for exc in targets.values()
                  if exc.series_id == rule.id}
        for day in sorted(dates):
            key = (rule.id, day)
            checked.add(key)
            found = origin(rule, day)
            target = targets.get(key)
            if found is None:
                if target is not None:
                    issues.append(EligibilityExpansionIssue(
                        "ORPHANED_ELIGIBILITY_EXCEPTION", rule.id, day))
                continue
            rev, start, end = found
            if target is not None:
                if target.action is EligibilityAction.REMOVE:
                    continue
                assert target.starts_at is not None and target.ends_at is not None
                start, end = (target.starts_at.astimezone(timezone.utc),
                              target.ends_at.astimezone(timezone.utc))
            source = f"ELIGIBILITY:{rule.id}:{day.isoformat()}:v{rev.number}"
            if target is not None:
                source += f":EXCEPTION:{target.id}:v{target.version}"
            occurrences.append(EligibilityOccurrence(
                rule.id, rev.number, day, start, end, rule.scope_id,
                rule.work_type_id, rev.priority_rank, source))
    for key in targets:
        if key not in checked:
            issues.append(EligibilityExpansionIssue(
                "ORPHANED_ELIGIBILITY_EXCEPTION", key[0], key[1]))
    return (
        tuple(sorted(occurrences, key=lambda item:
                     (item.starts_at, str(item.series_id), item.original_local_date))),
        tuple(sorted(issues, key=lambda item:
                     (item.original_local_date, str(item.series_id), item.code))),
    )
