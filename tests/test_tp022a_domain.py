"""TP-022A: deterministic bounded civil recurrence, including DST diagnostics."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleKind, RuleRevision, expand_rules,
)


def revision(day, *, number=1, **overrides):
    defaults = dict(
        rule_id=uuid4(), number=number, effective_from=day, valid_until=None,
        timezone_name="America/Toronto", days_of_week=(1, 3),
        starts_at_local="09:00", ends_at_local="11:30",
        kind=RuleKind.GENERAL, work_type_id=None, mode=None, enabled=True,
    )
    defaults.update(overrides)
    return RuleRevision(**defaults)


def test_weekly_tuesday_thursday_is_exactly_five_hours():
    monday = date(2027, 1, 4)
    rev = revision(monday)
    rule = RecurringAvailabilityRule(rev.rule_id, "owner", 1, (rev,))
    occurrences, issues = expand_rules((rule,), monday, monday + timedelta(days=7))
    assert issues == ()
    assert [value.original_local_date.weekday() for value in occurrences] == [1, 3]
    assert sum((value.ends_at - value.starts_at).total_seconds() for value in occurrences) == 18000
    assert all(value.starts_at.tzinfo == timezone.utc for value in occurrences)
    assert expand_rules((rule,), monday + timedelta(days=7), monday + timedelta(days=14))[0]


def test_future_revision_preserves_historical_occurrence():
    monday = date(2027, 1, 4)
    rule_id = uuid4()
    first = revision(monday, rule_id=rule_id)
    second = revision(monday + timedelta(days=7), number=2, rule_id=rule_id,
                      starts_at_local="10:00", ends_at_local="11:30")
    series = RecurringAvailabilityRule(rule_id, "owner", 2, (first, second))
    found, _ = expand_rules((series,), monday, monday + timedelta(days=14))
    assert [v.revision for v in found] == [1, 1, 2, 2]
    assert [v.starts_at.hour for v in found] == [14, 14, 15, 15]


def test_invalid_recurrence_and_limits():
    base = date(2027, 1, 4)
    with pytest.raises(ValueError, match="unique weekdays"):
        revision(base, days_of_week=(1, 1))
    with pytest.raises(ValueError, match="unknown IANA"):
        revision(base, timezone_name="Moon/Base")
    with pytest.raises(ValueError, match="general rules"):
        revision(base, mode=AvailabilityMode.PROTECTED)
    with pytest.raises(ValueError, match="require"):
        revision(base, kind=RuleKind.CATEGORIZED)
    with pytest.raises(ValueError, match="follow"):
        revision(base, starts_at_local="11:30", ends_at_local="09:00")
    with pytest.raises(ValueError, match="93 days"):
        expand_rules((), base, base + timedelta(days=94))


def test_dst_gap_and_fold_require_explicit_choice():
    gap_day = date(2027, 3, 14)
    gap = revision(gap_day, days_of_week=(6,), starts_at_local="02:30",
                   ends_at_local="03:30")
    found, issues = expand_rules(
        (RecurringAvailabilityRule(gap.rule_id, "owner", 1, (gap,)),),
        gap_day, gap_day + timedelta(days=1),
    )
    assert not found
    assert issues[0].reason == "NONEXISTENT_LOCAL_TIME"

    fold_day = date(2027, 11, 7)
    fold = revision(fold_day, days_of_week=(6,), starts_at_local="01:30",
                    ends_at_local="02:30")
    rule = RecurringAvailabilityRule(fold.rule_id, "owner", 1, (fold,))
    found, issues = expand_rules((rule,), fold_day, fold_day + timedelta(days=1))
    assert not found and issues[0].reason == "AMBIGUOUS_LOCAL_TIME"
    selected = revision(fold_day, rule_id=fold.rule_id, days_of_week=(6,),
                        starts_at_local="01:30", ends_at_local="02:30", start_fold=1)
    found, issues = expand_rules(
        (RecurringAvailabilityRule(fold.rule_id, "owner", 1, (selected,)),),
        fold_day, fold_day + timedelta(days=1),
    )
    assert not issues and len(found) == 1
    assert found[0].ends_at - found[0].starts_at == timedelta(hours=1)


def test_expired_and_disabled_series_do_not_materialize():
    monday = date(2027, 1, 4)
    rev = revision(monday, valid_until=monday + timedelta(days=2))
    rule = RecurringAvailabilityRule(rev.rule_id, "owner", 1, (rev,))
    assert len(expand_rules((rule,), monday, monday + timedelta(days=7))[0]) == 1
    disabled = revision(monday, enabled=False)
    rule = RecurringAvailabilityRule(disabled.rule_id, "owner", 1, (disabled,))
    assert expand_rules((rule,), monday, monday + timedelta(days=7))[0] == ()


def test_expired_future_revision_never_restores_older_schedule():
    first_day = date(2027, 1, 4)
    identity = uuid4()
    old = revision(first_day, rule_id=identity)
    temporary = revision(first_day + timedelta(days=7), rule_id=identity,
                         number=2, valid_until=first_day + timedelta(days=8))
    series = RecurringAvailabilityRule(identity, "owner", 2, (old, temporary))
    result, _ = expand_rules((series,), first_day + timedelta(days=14),
                             first_day + timedelta(days=21))
    assert result == ()
