"""TP-041 domain placement: no silent compromises and no calendar writes."""
from datetime import date, datetime
from uuid import uuid4

from app.domain.calendar import CalendarCommitment
from app.domain.capacity import AvailabilityBlock
from app.domain.model import Task, TaskSegment, TaskStatus
from app.domain.task_rules import TaskAggregate
from app.domain.time_blocks import ConfirmedTimeBlock, suggest_time_blocks


WEEK = date(2026, 10, 5)


def moment(day, hour, minute=0):
    return datetime.fromisoformat(f"2026-10-{day:02}T{hour:02}:{minute:02}:00-04:00")


def availability(start, end, work_type=None):
    return AvailabilityBlock(WEEK, start, end, work_type)


def test_calendar_union_minute_rounding_and_types_do_not_borrow_capacity():
    focus = uuid4()
    blocks = [
        availability(moment(5, 9), moment(5, 11), focus),
        availability(moment(5, 11), moment(5, 12)),
    ]
    events = [
        CalendarCommitment("primary", "a", "Meeting", moment(5, 9, 30), moment(5, 10)),
        CalendarCommitment("other", "b", "Overlap", moment(5, 9, 45), moment(5, 10, 30)),
    ]
    task = Task(title="Focus", work_type_id=focus, estimated_minutes=90)
    loose = Task(title="Unclassified", estimated_minutes=45)
    preview = suggest_time_blocks(WEEK, "America/Toronto", blocks, events, [], [
        TaskAggregate(task), TaskAggregate(loose),
    ])
    assert preview.can_confirm is False
    assert sum(s.minutes for s in preview.suggestions if s.task_id == task.id) == 60
    assert sum(s.minutes for s in preview.suggestions if s.task_id == loose.id) == 45
    assert preview.unplaced[0].remaining_minutes == 30
    assert all(s.work_type_id == focus for s in preview.suggestions if s.task_id == task.id)
    assert all(not (s.starts_at < e.ends_at and e.starts_at < s.ends_at)
               for s in preview.suggestions for e in events)


def test_splits_work_across_free_spans_preserving_user_order_and_deadline():
    focus = uuid4()
    blocks = [availability(moment(5, 9), moment(5, 10), focus),
              availability(moment(5, 11), moment(5, 12), focus)]
    first = Task(title="First", work_type_id=focus, estimated_minutes=80)
    second = Task(title="Second", work_type_id=focus, estimated_minutes=20,
                  due_at=moment(5, 11, 30))
    preview = suggest_time_blocks(WEEK, "America/Toronto", blocks, [], [], [
        TaskAggregate(first), TaskAggregate(second),
    ])
    assert preview.can_confirm
    assert [(s.task_id, s.minutes) for s in preview.suggestions] == [
        (first.id, 60), (first.id, 20), (second.id, 20),
    ]
    assert preview.suggestions[-1].ends_at <= second.due_at
    assert preview.fingerprint == suggest_time_blocks(
        WEEK, "America/Toronto", blocks, [], [], [
            TaskAggregate(first), TaskAggregate(second),
        ]
    ).fingerprint


def test_reserved_slots_and_unknown_estimates_are_not_silently_overwritten():
    focus = uuid4()
    manual = [availability(moment(5, 9), moment(5, 10), focus)]
    saved_task = Task(title="Saved", work_type_id=focus, estimated_minutes=15)
    reserved = ConfirmedTimeBlock(WEEK, saved_task.id, None, focus,
                                  moment(5, 9), moment(5, 9, 15))
    unknown = Task(title="Unknown", work_type_id=focus)
    preview = suggest_time_blocks(WEEK, "America/Toronto", manual, [], [reserved], [
        TaskAggregate(saved_task), TaskAggregate(unknown),
    ])
    assert not preview.can_confirm
    assert {u.reason for u in preview.unplaced} == {
        "ALREADY_CONFIRMED", "ESTIMATE_UNKNOWN",
    }
    assert not preview.suggestions


def test_segments_are_only_scheduled_as_open_leaf_units():
    task = Task(title="Parent", estimated_minutes=999)
    done = TaskSegment(task_id=task.id, title="Done", position=0, estimated_minutes=100,
                       status="DONE")
    opened = TaskSegment(task_id=task.id, title="Open", position=1, estimated_minutes=20)
    preview = suggest_time_blocks(
        WEEK, "UTC", [availability(moment(5, 9), moment(5, 10))], [], [],
        [TaskAggregate(task, (done, opened))],
    )
    assert preview.can_confirm
    assert len(preview.suggestions) == 1
    assert preview.suggestions[0].segment_id == opened.id
    assert preview.suggestions[0].minutes == 20


def test_event_seconds_round_outward_in_real_time_across_dst():
    week = date(2026, 10, 26)
    block = AvailabilityBlock(
        week, datetime.fromisoformat("2026-11-01T00:30:00-04:00"),
        datetime.fromisoformat("2026-11-01T02:30:00-05:00"),
    )
    event = CalendarCommitment(
        "a", "b", "Busy",
        datetime.fromisoformat("2026-11-01T01:30:10-04:00"),
        datetime.fromisoformat("2026-11-01T01:30:30-05:00"),
    )
    task = Task(title="DST", estimated_minutes=100)
    result = suggest_time_blocks(week, "America/Toronto", [block], [event], [],
                                 [TaskAggregate(task)])
    assert result.can_confirm
    assert sum(s.minutes for s in result.suggestions) == 100
    assert all(s.ends_at <= event.starts_at or s.starts_at >= event.ends_at
               for s in result.suggestions)
