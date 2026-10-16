"""TP-024A deterministic minute partition, civil time and preferred transfers."""
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.capacity import AvailabilityBlock
from app.domain.effective_availability import project_effective
from app.domain.model import Task, TaskStatus
from app.domain.recurring_availability import (
    RuleRevision, RecurringAvailabilityRule, RuleKind, AvailabilityMode,
)
from app.domain.schedule_scopes import ScopeAffiliation
from app.domain.task_rules import TaskAggregate
from app.domain.time_blocks import suggest_time_blocks

ZONE = "America/Toronto"
DAY = date(2026, 11, 2)  # first Monday after DST fallback


def rule(day, scope, weekday, begin, end, kind=RuleKind.GENERAL,
         work_type=None, mode=None):
    ident = uuid4()
    revision = RuleRevision(
        ident, 1, day, None, ZONE, (weekday,), begin, end,
        kind, work_type, mode, scope_id=scope,
    )
    return RecurringAvailabilityRule(ident, "owner", 1, (revision,))


def test_nonoverlapping_parents_have_isolated_null_buckets():
    a, b = uuid4(), uuid4()
    rules = (rule(DAY, a, 0, "09:00", "10:00"),
             rule(DAY, b, 1, "09:00", "10:00"))
    value = project_effective(rules, (), (), (), DAY, DAY+timedelta(days=7),
                              ZONE, compatibility_id=uuid4())
    assert value.declared_minutes == 120
    assert {(v.scope_id, v.work_type_id) for v in value.blocks} == {
        (a, None), (b, None),
    }


def test_overlap_is_not_double_counted_and_all_claimants_are_reported():
    a, b = uuid4(), uuid4()
    rules = (rule(DAY, a, 0, "09:00", "11:00"),
             rule(DAY, b, 0, "10:00", "12:00"))
    value = project_effective(rules, (), (), (), DAY, DAY+timedelta(days=1),
                              ZONE, compatibility_id=uuid4())
    assert value.declared_minutes == 120
    issue = next(e for e in value.issues if e.code == "INCOMPATIBLE_SCOPES")
    assert set(issue.scope_ids) == {a, b}
    assert (issue.ends_at-issue.starts_at).total_seconds() == 3600


def test_affiliation_outside_scope_is_not_schedulable():
    a, b, leaf, compatibility = uuid4(), uuid4(), uuid4(), uuid4()
    rules = (rule(DAY, a, 0, "09:00", "11:00"),
             rule(DAY, a, 0, "09:00", "10:00", RuleKind.CATEGORIZED,
                  leaf, AvailabilityMode.PREFERRED))
    affiliations = (ScopeAffiliation(leaf, b, "owner", DAY, 1),)
    projection = project_effective(rules, (), (), (), DAY, DAY+timedelta(days=1),
                                   ZONE, compatibility_id=compatibility,
                                   affiliations=affiliations)
    assert any(i.code == "AFFILIATION_SCOPE_MISMATCH" for i in projection.issues)
    assert projection.declared_minutes == 60


def test_cancel_occurrence_does_not_restore_null_of_its_parent():
    a, leaf, compat = uuid4(), uuid4(), uuid4()
    general = rule(DAY, a, 0, "09:00", "11:00")
    focused = rule(DAY, a, 0, "09:00", "10:00", RuleKind.CATEGORIZED,
                   leaf, AvailabilityMode.PREFERRED)
    cancel = AvailabilityException(
        uuid4(), "owner", 1, ExceptionAction.CANCEL,
        rule_id=focused.id, original_local_date=DAY, timezone_name=ZONE,
        scope_id=a,
    )
    result = project_effective(
        (general, focused), (cancel,), (), (), DAY, DAY+timedelta(days=1),
        ZONE, compatibility_id=compat,
        affiliations=(ScopeAffiliation(leaf, a, "owner", DAY, 1),),
    )
    assert result.declared_minutes == 60
    assert [b.minutes for b in result.blocks] == [60]


def test_global_unavailable_clips_all_parents_but_scoped_only_one():
    a, b = uuid4(), uuid4()
    rules = (rule(DAY, a, 0, "09:00", "10:00"),
             rule(DAY, b, 0, "10:00", "11:00"))
    start = datetime(2026, 11, 2, 9, 30, tzinfo=ZoneInfo(ZONE))
    stop = start+timedelta(minutes=30)
    scoped = AvailabilityException(
        uuid4(), "owner", 1, ExceptionAction.UNAVAILABLE,
        starts_at=start, ends_at=stop, timezone_name=ZONE, scope_id=a,
    )
    p = project_effective(rules, (scoped,), (), (), DAY, DAY+timedelta(days=1),
                          ZONE, compatibility_id=uuid4())
    assert p.declared_minutes == 90
    global_block = AvailabilityException(
        uuid4(), "owner", 1, ExceptionAction.UNAVAILABLE,
        starts_at=datetime(2026,11,2,10,15,tzinfo=ZoneInfo(ZONE)),
        ends_at=datetime(2026,11,2,10,45,tzinfo=ZoneInfo(ZONE)),
        timezone_name=ZONE,
    )
    total = project_effective(rules, (scoped, global_block), (), (), DAY,
                              DAY+timedelta(days=1), ZONE, compatibility_id=uuid4())
    assert total.declared_minutes == 60


def test_preferred_donation_is_intra_parent_not_cross_parent():
    a, b, donor, target = uuid4(), uuid4(), uuid4(), uuid4()
    day = DAY
    start = datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo(ZONE))
    availability = (AvailabilityBlock(
        day, start, start+timedelta(minutes=60), work_type_id=donor,
        scope_id=a),)
    task = Task(title="Planned task", status=TaskStatus.TODO, work_type_id=target,
                estimated_minutes=60)
    aggregate = TaskAggregate(task)
    forbidden = suggest_time_blocks(
        day, ZONE, availability, (), (), (aggregate,),
        preferred_blocks=availability, offer_transfers=True,
        work_type_scopes={donor:a, target:b},
    )
    assert not forbidden.suggestions and not forbidden.can_confirm
    allowed = suggest_time_blocks(
        day, ZONE, availability, (), (), (aggregate,),
        preferred_blocks=availability, offer_transfers=True,
        work_type_scopes={donor:a, target:a},
    )
    assert allowed.can_confirm
    assert allowed.suggestions[0].transferred_from == donor
