"""TP-022A: civil-time weekly series; declarations, never verified free capacity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AvailabilityMode(StrEnum):
    PROTECTED = "PROTECTED"
    PREFERRED = "PREFERRED"


class RuleKind(StrEnum):
    GENERAL = "GENERAL"
    CATEGORIZED = "CATEGORIZED"


class RuleConflict(Exception):
    """Optimistic concurrency conflict, returned as HTTP 409."""


def _wall_clock(value: str, *, end: bool = False) -> int:
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        if end and value == "24:00":
            return 1440
        raise ValueError("civil time must be HH:MM (end may be 24:00)")
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


@dataclass(frozen=True, slots=True)
class RuleRevision:
    rule_id: UUID
    number: int
    effective_from: date
    valid_until: date | None
    timezone_name: str
    days_of_week: tuple[int, ...]
    starts_at_local: str
    ends_at_local: str
    kind: RuleKind
    work_type_id: UUID | None
    mode: AvailabilityMode | None
    enabled: bool = True
    start_fold: int | None = None
    end_fold: int | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("revision number must be positive")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        if not self.days_of_week or len(set(self.days_of_week)) != len(self.days_of_week) or any(
            not isinstance(day, int) or isinstance(day, bool) or day < 0 or day > 6
            for day in self.days_of_week
        ):
            raise ValueError("days_of_week must contain unique weekdays from 0 to 6")
        if self.days_of_week != tuple(sorted(self.days_of_week)):
            raise ValueError("days_of_week must be sorted")
        if self.valid_until is not None and self.valid_until <= self.effective_from:
            raise ValueError("valid_until must be after effective_from (exclusive)")
        if _wall_clock(self.ends_at_local, end=True) <= _wall_clock(self.starts_at_local):
            raise ValueError("ends_at_local must follow starts_at_local")
        if self.kind is RuleKind.GENERAL:
            if self.work_type_id is not None or self.mode is not None:
                raise ValueError("general rules have no work type or protection mode")
        elif self.kind is RuleKind.CATEGORIZED:
            if self.work_type_id is None or self.mode is None:
                raise ValueError("categorized rules require work_type_id and mode")
        else:
            raise ValueError("invalid rule kind")
        if self.start_fold not in (None, 0, 1) or self.end_fold not in (None, 0, 1):
            raise ValueError("DST fold must be 0, 1 or omitted")


@dataclass(frozen=True, slots=True)
class RecurringAvailabilityRule:
    id: UUID
    owner_id: str
    version: int
    revisions: tuple[RuleRevision, ...]

    def __post_init__(self) -> None:
        if not self.owner_id or not self.revisions or self.version != len(self.revisions):
            raise ValueError("invalid recurring rule/version")
        if any(rev.rule_id != self.id or rev.number != i
               for i, rev in enumerate(self.revisions, start=1)):
            raise ValueError("revision identity/order mismatch")
        if any(a.effective_from >= b.effective_from
               for a, b in zip(self.revisions, self.revisions[1:])):
            raise ValueError("revisions must progress by effective date")


@dataclass(frozen=True, slots=True)
class Occurrence:
    rule_id: UUID
    revision: int
    original_local_date: date
    starts_at: datetime
    ends_at: datetime
    work_type_id: UUID | None
    kind: RuleKind
    mode: AvailabilityMode | None


@dataclass(frozen=True, slots=True)
class ExpansionIssue:
    rule_id: UUID
    revision: int
    original_local_date: date
    reason: str


def _instant(day: date, clock: str, zone: ZoneInfo, fold: int | None) -> datetime:
    minutes = _wall_clock(clock, end=True)
    if minutes == 1440:
        day += timedelta(days=1)
        minutes = 0
    naive = datetime.combine(day, time(minutes // 60, minutes % 60))
    valid: dict[int, datetime] = {}
    for choice in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=choice)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            valid[choice] = utc
    if not valid:
        raise ValueError("NONEXISTENT_LOCAL_TIME")
    if len(set(valid.values())) > 1 and fold is None:
        raise ValueError("AMBIGUOUS_LOCAL_TIME")
    return valid[fold if fold is not None else 0]


def expand_rules(
    rules: tuple[RecurringAvailabilityRule, ...],
    from_date: date,
    to_date: date,
) -> tuple[tuple[Occurrence, ...], tuple[ExpansionIssue, ...]]:
    """Expand [from_date,to_date) up to 93 civil days; do not merge or claim capacity.

    TP-022B will partition these raw declarations with envelopes, exceptions,
    legacy manual blocks and reservations into the one effective timeline.
    """
    days = (to_date - from_date).days
    if not 0 < days <= 93:
        raise ValueError("expansion requires 1 to 93 days")
    occurrences: list[Occurrence] = []
    issues: list[ExpansionIssue] = []
    for rule in rules:
        for i in range(days):
            day = from_date + timedelta(days=i)
            applicable = [
                rev for rev in rule.revisions
                if rev.effective_from <= day and
                (rev.valid_until is None or day < rev.valid_until)
            ]
            if not applicable:
                continue
            rev = applicable[-1]
            if not rev.enabled or day.weekday() not in rev.days_of_week:
                continue
            zone = ZoneInfo(rev.timezone_name)
            try:
                start = _instant(day, rev.starts_at_local, zone, rev.start_fold)
                end = _instant(day, rev.ends_at_local, zone, rev.end_fold)
                if end <= start:
                    raise ValueError("NON_POSITIVE_UTC_DURATION")
            except ValueError as exc:
                issues.append(ExpansionIssue(rule.id, rev.number, day, str(exc)))
                continue
            occurrences.append(Occurrence(
                rule.id, rev.number, day, start, end, rev.work_type_id,
                rev.kind, rev.mode,
            ))
    return (
        tuple(sorted(occurrences, key=lambda v: (v.starts_at, str(v.rule_id)))),
        tuple(sorted(issues, key=lambda v: (v.original_local_date, str(v.rule_id)))),
    )
