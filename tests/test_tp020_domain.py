from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domain import SegmentStatus, Task, TaskAggregate, TaskSegment, TaskStatus
from app.domain.capacity import (
    AvailabilityBlock, CapacityStatus, evaluate_week, validate_blocks,
)


WEEK = date(2026, 10, 5)


def moment(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(
        f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00-04:00"
    )


def block(start: int, end: int, work_type_id=None) -> AvailabilityBlock:
    return AvailabilityBlock(
        week_start=WEEK, starts_at=moment(5, start),
        ends_at=moment(5, end), work_type_id=work_type_id,
    )


def test_block_boundaries_validation_and_cross_type_overlap():
    first = block(8, 9)
    second = block(9, 10, uuid4())
    validate_blocks(WEEK, [second, first])
    assert first.minutes == 60
    with pytest.raises(ValueError, match="overlap"):
        validate_blocks(WEEK, [first, AvailabilityBlock(
            week_start=WEEK, starts_at=moment(5, 8, 30),
            ends_at=moment(5, 10), work_type_id=uuid4(),
        )])
    with pytest.raises(ValueError, match="Monday"):
        AvailabilityBlock(
            week_start=date(2026, 10, 6),
            starts_at=moment(6, 8), ends_at=moment(6, 9),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        AvailabilityBlock(
            week_start=WEEK,
            starts_at=datetime(2026, 10, 5, 8),
            ends_at=moment(5, 9),
        )
    with pytest.raises(ValueError, match="after"):
        block(9, 8)


def test_segment_leaf_selection_inheritance_and_no_double_counting():
    focus, light = uuid4(), uuid4()
    task = Task(title="Parent", work_type_id=focus, estimated_minutes=800)
    a = TaskSegment(task_id=task.id, title="First", position=0, estimated_minutes=20)
    b = TaskSegment(task_id=task.id, title="Override", position=1,
                    estimated_minutes=10, work_type_id=light)
    completed = TaskSegment(
        task_id=task.id, title="Done", position=2, estimated_minutes=999,
        status=SegmentStatus.DONE,
    )
    blocks = [block(8, 9, focus), block(9, 10, light)]
    result = evaluate_week(WEEK, blocks, [TaskAggregate(task, (a, b, completed))])
    by_type = {b.work_type_id: b for b in result.by_work_type}
    assert by_type[focus].known_demand_minutes == 20
    assert by_type[light].known_demand_minutes == 10
    assert result.known_demand_minutes == 30
    assert result.status is CapacityStatus.FEASIBLE


def test_estimation_unknown_not_zero_and_overage_takes_precedence():
    focus = uuid4()
    blocks = [block(8, 9, focus)]
    unknown = Task(title="Unestimated", work_type_id=focus)
    partial = evaluate_week(WEEK, blocks, [TaskAggregate(unknown)])
    assert partial.status is CapacityStatus.INCOMPLETE
    assert partial.unestimated_units == 1
    assert partial.known_demand_minutes == 0

    big = Task(title="Too big", work_type_id=focus, estimated_minutes=61)
    overloaded = evaluate_week(
        WEEK, blocks, [TaskAggregate(unknown), TaskAggregate(big)]
    )
    assert overloaded.status is CapacityStatus.OVER_CAPACITY
    assert overloaded.remaining_minutes == -1
    assert overloaded.unestimated_units == 1
    exact = Task(title="Exactly", work_type_id=focus, estimated_minutes=60)
    assert evaluate_week(WEEK, blocks, [TaskAggregate(exact)]).status is CapacityStatus.FEASIBLE


def test_terminal_segments_have_zero_open_work_and_unmatched_bucket_conflicts():
    task = Task(title="Review", estimated_minutes=120)
    segment = TaskSegment(
        task_id=task.id, title="Finished", status=SegmentStatus.DONE
    )
    result = evaluate_week(WEEK, [], [TaskAggregate(task, (segment,))])
    assert result.status is CapacityStatus.FEASIBLE
    assert result.known_demand_minutes == 0
    unmatched = evaluate_week(WEEK, [block(8, 9, uuid4())], [
        TaskAggregate(Task(title="Unclassified", estimated_minutes=10))
    ])
    assert unmatched.status is CapacityStatus.OVER_CAPACITY
    assert unmatched.remaining_minutes == 50  # 60 total less 10 demand, but wrong bucket


def test_invalid_candidate_and_duplicate_candidate_rejected():
    task = Task(title="Inbox", status=TaskStatus.INBOX)
    with pytest.raises(ValueError, match="open clarified"):
        evaluate_week(WEEK, [], [TaskAggregate(task)])
    open_task = TaskAggregate(Task(title="Open"))
    with pytest.raises(ValueError, match="unique"):
        evaluate_week(WEEK, [], [open_task, open_task])


def test_dst_offset_duration_is_elapsed_time_not_naive_wall_time():
    dst = AvailabilityBlock(
        week_start=date(2026, 10, 26),
        starts_at=datetime.fromisoformat("2026-11-01T00:00:00-04:00"),
        ends_at=datetime.fromisoformat("2026-11-01T03:00:00-05:00"),
    )
    assert dst.minutes == 240
