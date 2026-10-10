from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domain import (
    PlanningDecision, DecisionOutcome, ProtectionLevel,
    Task, TaskAggregate, TaskSegment,
)
from app.domain.capacity import AvailabilityBlock, CapacityStatus
from app.domain.planning import PlanOptionKind, propose_plan

WEEK = date(2026, 10, 5)


def block(work_type_id=None):
    return AvailabilityBlock(
        week_start=WEEK,
        starts_at=datetime.fromisoformat("2026-10-05T08:00:00-04:00"),
        ends_at=datetime.fromisoformat("2026-10-05T09:00:00-04:00"),
        work_type_id=work_type_id,
    )


def test_protected_work_never_deferred_but_flexible_option_recalculates():
    typ = uuid4()
    protected = TaskAggregate(Task(
        title="Protected", work_type_id=typ,
        protection=ProtectionLevel.PROTECTED, estimated_minutes=40,
    ))
    flexible = TaskAggregate(Task(
        title="Flexible", work_type_id=typ,
        protection=ProtectionLevel.FLEXIBLE, estimated_minutes=30,
        due_at=datetime.fromisoformat("2026-10-06T12:00:00Z"),
    ))
    proposal = propose_plan(WEEK, [block(typ)], [flexible, protected])
    assert proposal.baseline.status is CapacityStatus.OVER_CAPACITY
    assert [p.kind for p in proposal.options] == [
        PlanOptionKind.KEEP, PlanOptionKind.DEFER,
        PlanOptionKind.REVIEW_SCOPE, PlanOptionKind.CONSIDER_DELEGATION,
    ]
    deferred = proposal.options[1]
    assert deferred.excluded_task_ids == (flexible.task.id,)
    assert deferred.capacity.status is CapacityStatus.FEASIBLE
    assert deferred.capacity.known_demand_minutes == 40
    assert any("Échéance" in c for c in deferred.option.consequences)
    assert proposal.options[0].requires_confirmation is False
    assert deferred.requires_confirmation is True
    assert proposal.options[-1].capacity is None
    assert len(proposal.proposal.options) == len(proposal.options)
    bad = PlanningDecision(
        proposal_id=proposal.proposal.id, outcome=DecisionOutcome.ACCEPTED,
        option_id=uuid4(),
    )
    with pytest.raises(ValueError, match="does not belong"):
        bad.validate_against(proposal.proposal)


def test_protected_child_prevents_whole_task_deferral():
    parent = Task(title="Parent", protection=ProtectionLevel.FLEXIBLE, estimated_minutes=800)
    child = TaskSegment(
        task_id=parent.id, title="Critical",
        protection_override=ProtectionLevel.PROTECTED, estimated_minutes=70,
    )
    candidate = TaskAggregate(parent, (child,))
    proposed = propose_plan(WEEK, [block()], [candidate])
    assert proposed.baseline.known_demand_minutes == 70
    assert all(p.kind is not PlanOptionKind.DEFER for p in proposed.options)
    assert proposed.baseline.status is CapacityStatus.OVER_CAPACITY


def test_unknown_estimate_remains_incomplete_after_deferral():
    unknown = TaskAggregate(Task(title="Unknown", protection=ProtectionLevel.PROTECTED))
    big = TaskAggregate(Task(title="Big", protection=ProtectionLevel.REPLANNABLE,
                             estimated_minutes=90))
    result = propose_plan(WEEK, [block()], [unknown, big])
    assert result.baseline.status is CapacityStatus.OVER_CAPACITY
    defer = next(p for p in result.options if p.kind is PlanOptionKind.DEFER)
    assert defer.capacity.status is CapacityStatus.INCOMPLETE
    assert defer.capacity.unestimated_units == 1
    assert defer.capacity.known_demand_minutes == 0
    assert result.options[-1].kind is PlanOptionKind.CLARIFY_ESTIMATES
    assert result.options[-1].capacity is None


def test_only_keep_when_everything_feasible_and_protected_or_empty():
    protected = TaskAggregate(Task(title="Fixed", protection=ProtectionLevel.PROTECTED,
                                   estimated_minutes=20))
    assert [p.kind for p in propose_plan(WEEK, [block()], [protected]).options] == [PlanOptionKind.KEEP]
    empty = propose_plan(WEEK, [], [])
    assert len(empty.options) == 1
    assert empty.baseline.status is CapacityStatus.FEASIBLE


def test_rejected_invalid_candidates_and_week():
    from app.domain import TaskStatus
    with pytest.raises(ValueError, match="Monday"):
        propose_plan(date(2026, 10, 6), [], [])
    bad = TaskAggregate(Task(title="Inbox", status=TaskStatus.INBOX))
    with pytest.raises(ValueError, match="open clarified"):
        propose_plan(WEEK, [], [bad])
    open_task = TaskAggregate(Task(title="Duplicate"))
    with pytest.raises(ValueError, match="unique"):
        propose_plan(WEEK, [], [open_task, open_task])
