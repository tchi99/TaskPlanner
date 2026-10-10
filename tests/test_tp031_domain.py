from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domain.capacity import AvailabilityBlock, CapacityStatus
from app.domain.model import ProtectionLevel, SegmentStatus, Task, TaskSegment
from app.domain.morning import DueStatus, build_morning_brief
from app.domain.task_rules import TaskAggregate

DAY = date(2026, 10, 10)
WEEK = date(2026, 10, 5)


def block(start, end):
    return AvailabilityBlock(
        week_start=WEEK,
        starts_at=datetime.fromisoformat(start),
        ends_at=datetime.fromisoformat(end),
    )


def test_morning_brief_protection_deadlines_and_no_auto_deferral():
    parent = Task(title="Parent", protection=ProtectionLevel.FLEXIBLE,
                  due_at=datetime.fromisoformat("2026-10-12T12:00:00Z"))
    protected_segment = TaskSegment(
        task_id=parent.id, title="Critique",
        protection_override=ProtectionLevel.PROTECTED, estimated_minutes=80,
    )
    due = Task(title="Due today", protection=ProtectionLevel.REPLANNABLE,
               due_at=datetime.fromisoformat("2026-10-11T02:00:00Z"), estimated_minutes=20)
    late = Task(title="Late", protection=ProtectionLevel.FLEXIBLE,
                due_at=datetime.fromisoformat("2026-10-09T12:00:00Z"))
    flexible = Task(title="May slip", protection=ProtectionLevel.FLEXIBLE,
                    estimated_minutes=15)
    review = build_morning_brief(
        DAY, "America/Toronto",
        [block("2026-10-10T09:00:00-04:00", "2026-10-10T10:00:00-04:00")],
        [TaskAggregate(parent, (protected_segment,)), TaskAggregate(due),
         TaskAggregate(late), TaskAggregate(flexible)], 2,
    )
    assert review.today_available_minutes == 60
    assert review.weekly_if_all_open.status is CapacityStatus.OVER_CAPACITY
    assert review.weekly_if_all_open.known_demand_minutes == 115
    assert review.weekly_if_all_open.unestimated_units == 1
    assert {item.title for item in review.must_review} == {"Parent", "Due today", "Late"}
    assert [(item.title, item.due_status) for item in review.may_slip] == [
        ("May slip", DueStatus.NONE)
    ]
    assert next(item for item in review.must_review if item.title == "Parent").protection is ProtectionLevel.PROTECTED
    assert next(item for item in review.must_review if item.title == "Due today").due_status is DueStatus.TODAY
    assert [decision.code for decision in review.decisions] == [
        "OVERDUE", "TODAY_DUE", "POTENTIAL_OVERLOAD", "UNKNOWN_ESTIMATES", "INBOX", "SELECT_TODAY"
    ]


def test_no_availability_is_not_a_real_daily_overload_and_overnight_blocks_are_clipped():
    open_task = TaskAggregate(Task(title="Todo", estimated_minutes=20))
    no_blocks = build_morning_brief(DAY, "UTC", [], [open_task], 0)
    assert no_blocks.manual_block_count == 0
    assert no_blocks.today_available_minutes == 0
    assert no_blocks.weekly_if_all_open.status is CapacityStatus.OVER_CAPACITY
    assert "NO_BLOCKS" in [decision.code for decision in no_blocks.decisions]
    assert "POTENTIAL_OVERLOAD" not in [decision.code for decision in no_blocks.decisions]
    overnight = block("2026-10-09T23:00:00-04:00", "2026-10-10T01:00:00-04:00")
    review = build_morning_brief(DAY, "America/Toronto", [overnight], [], 0)
    assert review.today_available_minutes == 60
    assert review.weekly_if_all_open.status is CapacityStatus.FEASIBLE


def test_invalid_zone_and_non_open_candidates_rejected():
    with pytest.raises(ValueError, match="timezone"):
        build_morning_brief(DAY, "Not/A_Real_Zone", [], [], 0)
    from app.domain.model import TaskStatus
    with pytest.raises(ValueError, match="open clarified"):
        build_morning_brief(DAY, "UTC", [], [
            TaskAggregate(Task(title="Inbox", status=TaskStatus.INBOX))
        ], 0)
