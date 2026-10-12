"""TP-022B disjoint declared availability, exception priority and civil DST."""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.capacity import AvailabilityBlock
from app.domain.effective_availability import project_effective
from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleKind, RuleRevision,
)


MONDAY = date(2027, 1, 4)


def recurring(kind, work_type=None, *, days=(1, 3), start="09:00", end="12:00"):
    identity = uuid4()
    revision = RuleRevision(
        rule_id=identity, number=1, effective_from=MONDAY, valid_until=None,
        timezone_name="America/Toronto", days_of_week=days,
        starts_at_local=start, ends_at_local=end,
        kind=kind, work_type_id=work_type,
        mode=AvailabilityMode.PROTECTED if work_type is not None else None,
    )
    return RecurringAvailabilityRule(identity, "owner", 1, (revision,))


def exception(action, **overrides):
    data = dict(
        id=uuid4(), owner_id="owner", version=1, action=action,
        timezone_name="America/Toronto",
    )
    data.update(overrides)
    return AvailabilityException(**data)


def projected(rules=(), exceptions=(), manual=(), booked=(),
              start=MONDAY, end=MONDAY + timedelta(days=7)):
    return project_effective(rules, exceptions, manual, booked,
                             start, end, "America/Toronto")


def test_general_subdivided_not_added_and_duplicate_equivalent_not_double_counted():
    focus = uuid4()
    envelope = recurring(RuleKind.GENERAL)
    category = recurring(RuleKind.CATEGORIZED, focus, end="11:30")
    result = projected((envelope, category))
    assert result.declared_minutes == 360
    assert sum(b.minutes for b in result.blocks if b.work_type_id == focus) == 300
    assert sum(b.minutes for b in result.blocks if b.work_type_id is None) == 60
    assert not result.issues
    duplicate = recurring(RuleKind.GENERAL)
    assert projected((envelope, duplicate, category)).declared_minutes == 360


def test_cancel_single_tuesday_does_not_refill_general_bucket_and_thursday_remains():
    focus = uuid4()
    envelope = recurring(RuleKind.GENERAL)
    categorized = recurring(RuleKind.CATEGORIZED, focus, end="11:30")
    canceled = exception(ExceptionAction.CANCEL, rule_id=categorized.id,
                         original_local_date=MONDAY + timedelta(days=1))
    actual = projected((envelope, categorized), (canceled,))
    assert actual.declared_minutes == 210
    assert sum(b.minutes for b in actual.blocks if b.work_type_id == focus) == 150
    week_two = projected((envelope, categorized), (canceled,),
                         MONDAY + timedelta(days=7), MONDAY + timedelta(days=14))
    assert week_two.declared_minutes == 360


def test_move_occurrence_to_another_week_does_not_resurrect_original():
    rule = recurring(RuleKind.GENERAL, days=(1,))
    tuesday = MONDAY + timedelta(days=1)
    moved = exception(ExceptionAction.REPLACE, rule_id=rule.id,
                      original_local_date=tuesday,
                      starts_at=datetime.fromisoformat("2027-01-13T09:00:00-05:00"),
                      ends_at=datetime.fromisoformat("2027-01-13T12:00:00-05:00"),
                      kind=RuleKind.GENERAL)
    first = projected((rule,), (moved,))
    second = projected((rule,), (moved,),
                       MONDAY + timedelta(days=7), MONDAY + timedelta(days=14))
    assert first.declared_minutes == 0
    # Original Jan 12 occurrence still exists; the Jan 6 occurrence moved to Jan 13.
    assert second.declared_minutes == 360


def test_manual_overlap_has_provenance_not_duplicate_minutes_or_implicit_preference():
    envelope = recurring(RuleKind.GENERAL, days=(1,))
    other = recurring(RuleKind.CATEGORIZED, uuid4(), days=(1,))
    manual = AvailabilityBlock(
        week_start=MONDAY,
        starts_at=datetime.fromisoformat("2027-01-05T10:00:00-05:00"),
        ends_at=datetime.fromisoformat("2027-01-05T11:00:00-05:00"),
    )
    conflict = projected((envelope, other), manual=(manual,))
    assert "INCOMPATIBLE_WORK_TYPES" in [v.code for v in conflict.issues]
    assert conflict.declared_minutes == 120
    assert any("MANUAL:" in "|".join(v.sources) for v in conflict.issues)


def test_real_unavailability_beats_added_and_manual_capacity():
    manual = AvailabilityBlock(
        week_start=MONDAY,
        starts_at=datetime.fromisoformat("2027-01-04T09:00:00-05:00"),
        ends_at=datetime.fromisoformat("2027-01-04T11:00:00-05:00"),
    )
    unavailable = exception(
        ExceptionAction.UNAVAILABLE,
        starts_at=datetime.fromisoformat("2027-01-04T09:30:00-05:00"),
        ends_at=datetime.fromisoformat("2027-01-04T10:30:00-05:00"),
    )
    actual = projected(exceptions=(unavailable,), manual=(manual,))
    assert actual.declared_minutes == 60
    assert "DECLARED_UNAVAILABLE" in [v.code for v in actual.issues]


def test_nonexistent_dst_local_wall_time_is_rejected_without_normalization():
    with pytest.raises(ValueError, match="DST"):
        exception(
            ExceptionAction.UNAVAILABLE,
            starts_at=datetime.fromisoformat("2027-03-14T02:30:00-05:00"),
            ends_at=datetime.fromisoformat("2027-03-14T03:30:00-04:00"),
        )
    valid = exception(
        ExceptionAction.UNAVAILABLE,
        starts_at=datetime.fromisoformat("2027-11-07T01:30:00-05:00"),
        ends_at=datetime.fromisoformat("2027-11-07T02:30:00-05:00"),
    )
    assert valid.starts_at.utcoffset() == timedelta(hours=-5)
