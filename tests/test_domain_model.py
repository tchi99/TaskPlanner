from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain import (
    Constraint,
    ConstraintKind,
    DecisionOutcome,
    PlanningDecision,
    PlanningOption,
    PlanningProposal,
    Project,
    ProtectionLevel,
    Task,
    TaskSegment,
    WorkType,
)


def test_project_requires_a_title() -> None:
    with pytest.raises(ValueError, match="title"):
        Project(title="   ")


def test_work_type_is_user_defined_domain_data() -> None:
    work_type = WorkType(name="Deep work", description="Focused work")
    assert work_type.name == "Deep work"


def test_task_defaults_to_replannable_and_todo() -> None:
    task = Task(title="Prepare weekly plan")
    assert task.protection is ProtectionLevel.REPLANNABLE
    assert task.status.value == "TODO"


def test_task_estimate_must_be_positive() -> None:
    with pytest.raises(ValueError, match="estimated_minutes"):
        Task(title="Invalid", estimated_minutes=0)


def test_task_due_date_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="due_at"):
        Task(title="Invalid", due_at=datetime(2026, 9, 26, 9, 0))


def test_segment_belongs_to_a_task_and_has_its_own_estimate() -> None:
    task_id = uuid4()
    segment = TaskSegment(
        task_id=task_id,
        title="Open the document",
        estimated_minutes=10,
    )
    assert segment.task_id == task_id
    assert segment.estimated_minutes == 10


def test_constraint_rejects_invalid_time_window() -> None:
    start = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="ends_at"):
        Constraint(
            title="Meeting",
            kind=ConstraintKind.TIME_BLOCK,
            starts_at=start,
            ends_at=start,
        )


def test_planning_proposal_requires_at_least_one_option() -> None:
    with pytest.raises(ValueError, match="at least one option"):
        PlanningProposal(options=())


def test_rejected_decision_cannot_select_an_option() -> None:
    with pytest.raises(ValueError, match="must not select"):
        PlanningDecision(
            proposal_id=uuid4(),
            outcome=DecisionOutcome.REJECTED,
            option_id=uuid4(),
        )


def test_accepted_decision_must_reference_an_option_from_proposal() -> None:
    option = PlanningOption(
        label="Move flexible task",
        rationale="Protect the fixed deadline",
    )
    proposal = PlanningProposal(options=(option,))

    valid = PlanningDecision(
        proposal_id=proposal.id,
        outcome=DecisionOutcome.ACCEPTED,
        option_id=option.id,
    )
    valid.validate_against(proposal)

    invalid = PlanningDecision(
        proposal_id=proposal.id,
        outcome=DecisionOutcome.ACCEPTED,
        option_id=uuid4(),
    )
    with pytest.raises(ValueError, match="does not belong"):
        invalid.validate_against(proposal)


def test_proposal_and_decision_remain_separate_objects() -> None:
    option = PlanningOption(
        label="Keep current plan",
        rationale="No conflict exists",
    )
    proposal = PlanningProposal(options=(option,), facts=("capacity is sufficient",))
    decision = PlanningDecision(
        proposal_id=proposal.id,
        outcome=DecisionOutcome.ACCEPTED,
        option_id=option.id,
    )

    assert proposal.options == (option,)
    assert decision.proposal_id == proposal.id
    assert proposal.id != decision.id
