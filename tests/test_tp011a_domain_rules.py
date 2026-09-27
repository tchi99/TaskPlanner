from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain import (
    DomainFactType,
    EstimateSource,
    FactRole,
    NextActionType,
    Project,
    ProjectStatus,
    ProtectionLevel,
    SegmentStatus,
    Task,
    TaskAggregate,
    TaskSegment,
    TaskStatus,
    WorkTypeOrigin,
    complete_project,
)


def _aggregate(
    *, status: TaskStatus = TaskStatus.TODO, estimate: int | None = None
) -> TaskAggregate:
    return TaskAggregate(
        Task(title="Parent", status=status, estimated_minutes=estimate)
    )


def test_clarification_preserves_capture_identity_and_created_at() -> None:
    created_at = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    task = Task(
        title="Captured", status=TaskStatus.INBOX, created_at=created_at
    )

    result = TaskAggregate(task).clarify()

    assert result.value.task.id == task.id
    assert result.value.task.created_at == created_at
    assert result.value.task.status is TaskStatus.TODO
    assert [fact.event_type for fact in result.facts] == [
        DomainFactType.TASK_CLARIFIED
    ]


def test_segment_status_is_distinct_and_does_not_allow_inbox() -> None:
    segment = TaskSegment(task_id=uuid4(), title="Step")
    assert segment.status is SegmentStatus.TODO
    assert "INBOX" not in SegmentStatus.__members__
    with pytest.raises(ValueError):
        TaskSegment(
            task_id=uuid4(),
            title="Invalid",
            status="INBOX",  # type: ignore[arg-type]
        )


def test_starting_segment_progresses_parent_and_marks_propagation() -> None:
    added = _aggregate().add_segment("First").value
    segment_id = added.segments[0].id

    result = added.start_segment(segment_id)

    assert result.value.task.status is TaskStatus.IN_PROGRESS
    assert result.value.segments[0].status is SegmentStatus.IN_PROGRESS
    assert [fact.event_type for fact in result.facts] == [
        DomainFactType.SEGMENT_STARTED,
        DomainFactType.TASK_STARTED,
    ]
    assert [fact.role for fact in result.facts] == [
        FactRole.DIRECT,
        FactRole.PROPAGATED,
    ]


def test_completing_todo_segment_progresses_parent_without_fake_start() -> None:
    added = _aggregate().add_segment("First").value
    segment_id = added.segments[0].id

    result = added.complete_segment(segment_id)

    assert result.value.task.status is TaskStatus.IN_PROGRESS
    assert result.value.segments[0].status is SegmentStatus.DONE
    assert [fact.event_type for fact in result.facts] == [
        DomainFactType.SEGMENT_COMPLETED,
        DomainFactType.TASK_STARTED,
    ]
    assert DomainFactType.SEGMENT_STARTED not in {
        fact.event_type for fact in result.facts
    }


def test_last_completed_segment_makes_task_ready_but_not_done() -> None:
    added = _aggregate().add_segment("Only").value
    result = added.complete_segment(added.segments[0].id)

    assert result.value.ready_for_completion()
    assert result.value.task.status is TaskStatus.IN_PROGRESS
    assert (
        result.value.next_action().action_type
        is NextActionType.REVIEW_COMPLETION
    )


def test_cancelling_all_segments_does_not_complete_task() -> None:
    aggregate = _aggregate().add_segment("A").value
    aggregate = aggregate.add_segment("B").value
    for segment in tuple(aggregate.segments):
        aggregate = aggregate.cancel_segment(segment.id).value

    assert aggregate.task.status is TaskStatus.TODO
    assert aggregate.ready_for_completion()
    assert aggregate.next_action().action_type is NextActionType.REVIEW_COMPLETION


def test_task_completion_is_explicit_and_requires_no_open_segments() -> None:
    aggregate = _aggregate().add_segment("A").value
    with pytest.raises(ValueError, match="segment remains open"):
        aggregate.complete()
    assert aggregate.task.status is TaskStatus.TODO

    aggregate = aggregate.complete_segment(aggregate.segments[0].id).value
    result = aggregate.complete()
    assert result.value.task.status is TaskStatus.DONE
    assert [fact.event_type for fact in result.facts] == [
        DomainFactType.TASK_COMPLETED
    ]


def test_task_cancellation_keeps_segments() -> None:
    aggregate = _aggregate().add_segment("A").value
    result = aggregate.cancel()

    assert result.value.task.status is TaskStatus.CANCELLED
    assert result.value.segments == aggregate.segments


def test_task_reopen_is_explicit_and_preserves_progress_semantics() -> None:
    aggregate = _aggregate().add_segment("A").value
    aggregate = aggregate.complete_segment(aggregate.segments[0].id).value
    aggregate = aggregate.complete().value

    result = aggregate.reopen()

    assert result.value.task.status is TaskStatus.IN_PROGRESS
    assert result.facts[0].event_type is DomainFactType.TASK_REOPENED


def test_segment_positions_are_unique_and_reordering_preserves_ids() -> None:
    aggregate = _aggregate().add_segment("A").value
    aggregate = aggregate.add_segment("B").value
    first, second = aggregate.segments

    reordered = aggregate.reorder_segments((second.id, first.id)).value
    ordered = sorted(reordered.segments, key=lambda segment: segment.position)

    assert [segment.id for segment in ordered] == [second.id, first.id]
    assert {segment.id for segment in reordered.segments} == {
        first.id,
        second.id,
    }
    assert [segment.position for segment in ordered] == [0, 1]

    with pytest.raises(ValueError, match="position"):
        TaskAggregate(
            task=aggregate.task,
            segments=(
                TaskSegment(
                    task_id=aggregate.task.id, title="X", position=0
                ),
                TaskSegment(
                    task_id=aggregate.task.id, title="Y", position=0
                ),
            ),
        )


def test_segment_cannot_belong_to_another_task() -> None:
    task = Task(title="Parent")
    with pytest.raises(ValueError, match="task_id"):
        TaskAggregate(
            task,
            (TaskSegment(task_id=uuid4(), title="Foreign"),),
        )


def test_effective_estimate_uses_task_when_no_active_segment() -> None:
    projection = _aggregate(estimate=120).effective_estimate()

    assert projection.source is EstimateSource.TASK
    assert projection.known_subtotal_minutes == 120
    assert projection.unestimated_units == 0
    assert projection.total_minutes == 120
    assert not projection.incomplete


def test_effective_estimate_uses_segments_without_parent_double_count() -> None:
    aggregate = _aggregate(estimate=120)
    aggregate = aggregate.add_segment("A", estimated_minutes=20).value
    aggregate = aggregate.add_segment("B", estimated_minutes=30).value

    projection = aggregate.effective_estimate()

    assert projection.source is EstimateSource.SEGMENTS
    assert projection.known_subtotal_minutes == 50
    assert projection.unestimated_units == 0
    assert projection.total_minutes == 50


def test_effective_estimate_remains_unknown_with_unknown_segment() -> None:
    aggregate = _aggregate(estimate=120)
    aggregate = aggregate.add_segment("A", estimated_minutes=20).value
    aggregate = aggregate.add_segment("B", estimated_minutes=None).value

    projection = aggregate.effective_estimate()

    assert projection.source is EstimateSource.SEGMENTS
    assert projection.known_subtotal_minutes == 20
    assert projection.unestimated_units == 1
    assert projection.total_minutes is None
    assert projection.incomplete


def test_none_task_estimate_stays_unknown_not_zero() -> None:
    projection = _aggregate(estimate=None).effective_estimate()

    assert projection.known_subtotal_minutes == 0
    assert projection.unestimated_units == 1
    assert projection.total_minutes is None
    assert projection.incomplete


def test_estimate_returns_to_task_source_when_no_active_segment_remains() -> None:
    aggregate = _aggregate(estimate=120).add_segment(
        "A", estimated_minutes=20
    ).value
    aggregate = aggregate.complete_segment(aggregate.segments[0].id).value

    projection = aggregate.effective_estimate()

    assert projection.source is EstimateSource.TASK
    assert projection.total_minutes == 120


def test_next_action_for_inbox_is_clarify() -> None:
    action = _aggregate(status=TaskStatus.INBOX).next_action()
    assert action.action_type is NextActionType.CLARIFY_TASK


def test_next_action_for_terminal_task_is_none() -> None:
    assert _aggregate(status=TaskStatus.DONE).next_action() is None
    assert _aggregate(status=TaskStatus.CANCELLED).next_action() is None


def test_next_action_for_task_without_segments_targets_task() -> None:
    aggregate = _aggregate()
    action = aggregate.next_action()

    assert action.action_type is NextActionType.WORK_ON_TASK
    assert action.target_id == aggregate.task.id


def test_next_action_prefers_first_in_progress_segment_by_position() -> None:
    aggregate = _aggregate()
    aggregate = aggregate.add_segment("Later", position=5).value
    aggregate = aggregate.add_segment("Earlier", position=2).value
    later, earlier = aggregate.segments
    aggregate = aggregate.start_segment(later.id).value
    aggregate = aggregate.start_segment(earlier.id).value

    action = aggregate.next_action()
    assert action.target_id == earlier.id


def test_next_action_uses_first_todo_segment_by_position() -> None:
    aggregate = _aggregate()
    aggregate = aggregate.add_segment("Later", position=5).value
    aggregate = aggregate.add_segment("Earlier", position=2).value

    action = aggregate.next_action()
    assert action.target_id == aggregate.segments[1].id


def test_next_action_reviews_completion_when_no_segment_is_open() -> None:
    aggregate = _aggregate().add_segment("A").value
    aggregate = aggregate.complete_segment(aggregate.segments[0].id).value

    assert aggregate.next_action().action_type is NextActionType.REVIEW_COMPLETION


def test_effective_work_type_inherits_overrides_or_is_unclassified() -> None:
    parent_type = uuid4()
    override_type = uuid4()
    aggregate = TaskAggregate(Task(title="Parent", work_type_id=parent_type))
    aggregate = aggregate.add_segment("Inherited").value
    aggregate = aggregate.add_segment(
        "Override", work_type_id=override_type
    ).value

    inherited = aggregate.effective_segment_work_type(
        aggregate.segments[0].id
    )
    override = aggregate.effective_segment_work_type(
        aggregate.segments[1].id
    )

    assert (inherited.work_type_id, inherited.origin) == (
        parent_type,
        WorkTypeOrigin.TASK_INHERITED,
    )
    assert (override.work_type_id, override.origin) == (
        override_type,
        WorkTypeOrigin.SEGMENT_OVERRIDE,
    )

    unclassified = _aggregate().add_segment("None").value
    projection = unclassified.effective_segment_work_type(
        unclassified.segments[0].id
    )
    assert projection.work_type_id is None
    assert projection.origin is WorkTypeOrigin.UNCLASSIFIED


def test_segment_effective_protection_is_inherited_from_task() -> None:
    task = Task(title="Protected", protection=ProtectionLevel.PROTECTED)
    aggregate = TaskAggregate(task).add_segment("A").value

    assert (
        aggregate.effective_segment_protection(aggregate.segments[0].id)
        is ProtectionLevel.PROTECTED
    )


def test_noop_task_estimate_and_work_type_changes_emit_no_fact() -> None:
    work_type_id = uuid4()
    task = Task(
        title="Parent",
        estimated_minutes=45,
        work_type_id=work_type_id,
    )
    aggregate = TaskAggregate(task)

    estimate = aggregate.change_task_estimate(45)
    work_type = aggregate.change_task_work_type(work_type_id)

    assert estimate.value is aggregate
    assert estimate.facts == ()
    assert work_type.value is aggregate
    assert work_type.facts == ()


def test_noop_segment_changes_emit_no_fact() -> None:
    work_type_id = uuid4()
    aggregate = _aggregate().add_segment(
        "A", estimated_minutes=45, work_type_id=work_type_id
    ).value
    segment = aggregate.segments[0]

    assert aggregate.change_segment_estimate(segment.id, 45).facts == ()
    assert (
        aggregate.change_segment_work_type(segment.id, work_type_id).facts
        == ()
    )


def test_invalid_mutation_leaves_original_state_unchanged() -> None:
    aggregate = _aggregate().add_segment("A").value
    snapshot = aggregate

    with pytest.raises(ValueError):
        aggregate.start()

    assert aggregate == snapshot


def test_fact_contract_is_versioned_and_structured() -> None:
    result = _aggregate().change_task_estimate(45)
    fact = result.facts[0]

    assert fact.event_type is DomainFactType.TASK_ESTIMATE_CHANGED
    assert fact.schema_version == 1
    assert fact.task_id == result.value.task.id
    assert fact.payload.before is None
    assert fact.payload.after == 45


def test_project_completion_refuses_open_work_and_never_mutates_tasks() -> None:
    project = Project(title="P")

    with pytest.raises(ValueError, match="work remains open"):
        complete_project(project, [TaskStatus.DONE, TaskStatus.TODO])

    assert project.status is ProjectStatus.ACTIVE

    completed = complete_project(
        project,
        [TaskStatus.DONE, TaskStatus.CANCELLED],
    )
    assert completed.status is ProjectStatus.COMPLETED
    assert project.status is ProjectStatus.ACTIVE
