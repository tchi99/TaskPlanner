"""TP-025A opt-in admission alternatives never manufacture physical minutes."""
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.domain.effective_availability import project_effective
from app.domain.eligibility import (
    EligibilityAction, EligibilityException, EligibilityRevision, EligibilitySeries,
    expand_eligibility,
)
from app.domain.eligibility_projection import project_eligibility
from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleKind, RuleRevision,
)
from app.domain.schedule_scopes import ScopeAffiliation, compatibility_scope_id


START = date(2027, 1, 4)  # Monday


def series(scope, work_type, *, days=(1,), start="10:00", end="12:00",
           rank=None, series_id=None, from_date=START):
    sid = series_id or uuid4()
    revision = EligibilityRevision(
        sid, 1, from_date, None, "America/Toronto",
        days, start, end, rank,
    )
    return EligibilitySeries(sid, "owner", scope, work_type, 1, (revision,))


def legacy(scope, *, kind=RuleKind.GENERAL, work_type=None, mode=None):
    rid = uuid4()
    revision = RuleRevision(
        rid, 1, START, None, "America/Toronto", (1,),
        "09:00", "17:00", kind, work_type, mode,
        scope_id=scope,
    )
    return RecurringAvailabilityRule(rid, "owner", 1, (revision,))


def projection(rules, series_values, exceptions=(), affiliations=()):
    scope = compatibility_scope_id("owner")
    original = project_effective(
        rules, (), (), (), START, START + timedelta(days=7),
        "America/Toronto", compatibility_id=scope, affiliations=affiliations,
    )
    return project_eligibility(
        original, series_values, exceptions, START, START + timedelta(days=7),
        "America/Toronto", compatibility_id=scope, affiliations=affiliations,
    )


def test_two_or_three_admissions_share_one_physical_120_minute_span():
    scope = compatibility_scope_id("owner")
    types = [uuid4() for _ in range(3)]
    p = projection((legacy(scope),), tuple(series(scope, typ) for typ in types))
    shared = [f for f in p.fragments if len(f.choices) == 3]
    assert len(shared) == 1
    assert shared[0].minutes == 120
    assert p.physical_minutes == 480
    assert dict(p.potential_minutes) == {typ: 120 for typ in types}
    assert shared[0].verification == "DECLARED_ONLY"
    assert not p.issues


def test_priority_is_local_and_other_days_are_neutral():
    scope = compatibility_scope_id("owner")
    focus, meetings = uuid4(), uuid4()
    p = projection(
        (legacy(scope),),
        (series(scope, focus, days=(1,), rank=1),
         series(scope, meetings, days=(1,), rank=2)),
    )
    both = next(f for f in p.fragments if len(f.choices) == 2)
    assert {v.work_type_id: v.priority_rank for v in both.choices} == {
        focus: 1, meetings: 2,
    }
    neutral = projection(
        (legacy(scope),),
        (series(scope, focus), series(scope, meetings)),
    )
    assert all(choice.priority_rank is None for f in neutral.fragments
               for choice in f.choices)


def test_remove_only_its_permission_and_restores_null_residual():
    scope = compatibility_scope_id("owner")
    focus, meetings = uuid4(), uuid4()
    first = series(scope, focus)
    second = series(scope, meetings)
    removed = EligibilityException(
        uuid4(), "owner", first.id, START + timedelta(days=1), 1,
        EligibilityAction.REMOVE, "America/Toronto",
    )
    p = projection((legacy(scope),), (first, second), (removed,))
    assert dict(p.potential_minutes) == {meetings: 120}
    alone = projection((legacy(scope),), (first,), (removed,))
    assert alone.physical_minutes == 480
    assert dict(alone.potential_minutes) == {}
    # REMOVE restores the entire unclaimed physical envelope to NULL. The
    # timeline may coalesce adjacent residual minutes into a single fragment.
    assert sum(f.minutes for f in alone.fragments if f.null_residual) == 480
    assert all(not f.choices for f in alone.fragments)


def test_conflicting_rank_same_type_is_diagnostic_not_uuid_tiebreak():
    scope = compatibility_scope_id("owner")
    focus = uuid4()
    p = projection(
        (legacy(scope),),
        (series(scope, focus, rank=1), series(scope, focus, rank=3)),
    )
    assert "CONFLICTING_ELIGIBILITY_RANKS" in {v.code for v in p.issues}
    assert not p.potential_minutes


def test_legacy_exclusive_is_not_reinterpreted_as_shared():
    scope = compatibility_scope_id("owner")
    focus, meetings = uuid4(), uuid4()
    p = projection(
        (legacy(scope), legacy(scope, kind=RuleKind.CATEGORIZED,
                               work_type=focus, mode=AvailabilityMode.PROTECTED)),
        (series(scope, meetings),),
    )
    assert "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE" in {v.code for v in p.issues}
    assert dict(p.potential_minutes) == {focus: 480}
    assert all(f.choices[0].exclusive for f in p.fragments)
    assert all(f.choices[0].legacy_mode is AvailabilityMode.PROTECTED
               for f in p.fragments)


def test_scope_affiliation_and_missing_envelope_are_diagnostics():
    scope = uuid4()
    focus = uuid4()
    value = series(scope, focus)
    p = projection((legacy(scope),), (value,))
    assert "ELIGIBILITY_AFFILIATION_MISMATCH" in {i.code for i in p.issues}
    p = projection((legacy(scope),), (value,),
                   affiliations=(ScopeAffiliation(focus, scope, "owner", START, 1),))
    assert not p.issues
    no_envelope = projection((), (series(compatibility_scope_id("owner"), uuid4()),))
    assert no_envelope.physical_minutes == 0
    assert "ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE" in {
        i.code for i in no_envelope.issues}


def test_dst_missing_and_ambiguous_instants_never_invent_capacity():
    scope = uuid4()
    spring = series(scope, uuid4(), from_date=date(2027, 3, 14),
                    days=(6,), start="02:30", end="03:30")
    occurrences, issues = expand_eligibility(
        (spring,), (), date(2027, 3, 14), date(2027, 3, 15))
    assert not occurrences and issues[0].code == "NONEXISTENT_LOCAL_TIME"
    autumn = series(scope, uuid4(), from_date=date(2027, 11, 7),
                    days=(6,), start="01:30", end="02:30")
    occurrences, issues = expand_eligibility(
        (autumn,), (), date(2027, 11, 7), date(2027, 11, 8))
    assert not occurrences and issues[0].code == "AMBIGUOUS_LOCAL_TIME"
    rev = replace(autumn.revisions[0], start_fold=1)
    found, issues = expand_eligibility(
        (replace(autumn, revisions=(rev,)),),
        (), date(2027, 11, 7), date(2027, 11, 8))
    assert len(found) == 1 and not issues
    assert found[0].ends_at - found[0].starts_at == timedelta(hours=1)


def test_revisions_are_temporal_not_retroactive():
    scope = uuid4()
    first = series(scope, uuid4())
    second_rev = replace(first.revisions[0], number=2,
                         effective_from=START + timedelta(days=7), priority_rank=1)
    value = replace(first, version=2, revisions=(first.revisions[0], second_rev))
    found, issues = expand_eligibility(
        (value,), (), START, START + timedelta(days=14))
    assert not issues
    assert [item.priority_rank for item in found] == [None, 1]
    with pytest.raises(ValueError, match="positive"):
        replace(first.revisions[0], priority_rank=0)
    with pytest.raises(ValueError, match="93 days"):
        expand_eligibility((first,), (), START, START + timedelta(days=94))


def test_new_admission_cannot_use_legacy_manual_null_block():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.domain.capacity import AvailabilityBlock

    scope = compatibility_scope_id("owner")
    zone = ZoneInfo("America/Toronto")
    manual = AvailabilityBlock(
        week_start=START,
        starts_at=datetime(2027, 1, 5, 10, tzinfo=zone),
        ends_at=datetime(2027, 1, 5, 12, tzinfo=zone),
        work_type_id=None,
    )
    old = project_effective(
        (), (), (manual,), (), START, START + timedelta(days=7),
        "America/Toronto", compatibility_id=scope,
    )
    result = project_eligibility(
        old, (series(scope, uuid4()),), (), START, START + timedelta(days=7),
        "America/Toronto", compatibility_id=scope,
    )
    assert result.physical_minutes == 120
    assert not result.potential_minutes
    assert "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE" in {v.code for v in result.issues}


def test_move_one_permission_and_keep_the_other_original():
    from datetime import datetime, timezone
    scope = compatibility_scope_id("owner")
    focus, meetings = uuid4(), uuid4()
    f = series(scope, focus)
    m = series(scope, meetings)
    exc = EligibilityException(
        uuid4(), "owner", f.id, START + timedelta(days=1), 1,
        EligibilityAction.MOVE, "America/Toronto",
        datetime(2027, 1, 5, 18, tzinfo=timezone.utc),
        datetime(2027, 1, 5, 20, tzinfo=timezone.utc),
    )
    result = projection((legacy(scope),), (f, m), (exc,))
    fragments = [v for v in result.fragments if any(
        c.work_type_id == focus for c in v.choices)]
    assert len(fragments) == 1
    assert fragments[0].starts_at.hour == 18
    assert dict(result.potential_minutes) == {focus: 120, meetings: 120}

