from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from app.domain import DomainFactType, ProtectionLevel, Task, TaskAggregate, TaskStatus
from app.domain.protection import assess_displacement

UTC = timezone.utc


def instant(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def test_task_and_segment_protection_are_explicit_and_inherit_with_floor():
    aggregate = TaskAggregate(Task(title="Plan", protection=ProtectionLevel.FLEXIBLE))
    changed = aggregate.change_task_protection(ProtectionLevel.REPLANNABLE)
    assert changed.facts[0].event_type is DomainFactType.TASK_PROTECTION_CHANGED
    assert changed.value.change_task_protection(ProtectionLevel.REPLANNABLE).facts == ()
    aggregate = changed.value.add_segment("Part").value
    segment_id = aggregate.segments[0].id
    assert aggregate.effective_segment_protection(segment_id) is ProtectionLevel.REPLANNABLE
    changed = aggregate.change_segment_protection(segment_id, ProtectionLevel.PROTECTED)
    assert changed.facts[0].event_type is DomainFactType.SEGMENT_PROTECTION_CHANGED
    assert changed.value.effective_segment_protection(segment_id) is ProtectionLevel.PROTECTED
    aggregate = changed.value.change_segment_protection(segment_id, None).value
    assert aggregate.effective_segment_protection(segment_id) is ProtectionLevel.REPLANNABLE
    aggregate = aggregate.change_task_protection(ProtectionLevel.PROTECTED).value
    aggregate = aggregate.change_segment_protection(segment_id, ProtectionLevel.FLEXIBLE).value
    assert aggregate.effective_segment_protection(segment_id) is ProtectionLevel.PROTECTED
    assert aggregate.change_segment_protection(segment_id, ProtectionLevel.FLEXIBLE).facts == ()


def test_preview_protected_with_deadline_and_unknown_effort_never_mutates():
    task = Task(
        title="Important", status=TaskStatus.TODO, protection=ProtectionLevel.PROTECTED,
        due_at=instant(12), estimated_minutes=None,
    )
    aggregate = TaskAggregate(task)
    result = assess_displacement(aggregate, instant(11), instant(13))
    assert result.reason_code == "PROTECTED_COMMITMENT"
    assert result.deadline_crossed is True
    assert result.starts_after_deadline is True
    assert result.delay_minutes == 2880
    assert result.estimate_unknown is True
    assert result.confirmation_required is True
    assert aggregate.task == task


def test_preview_task_level_respects_protected_child_and_rejects_closed_child():
    aggregate = TaskAggregate(Task(title="Flexible", protection=ProtectionLevel.FLEXIBLE))
    aggregate = aggregate.add_segment("Critical", protection_override=ProtectionLevel.PROTECTED).value
    identifier = aggregate.segments[0].id
    preview = assess_displacement(aggregate, instant(10), instant(11))
    assert preview.protection is ProtectionLevel.PROTECTED
    assert assess_displacement(aggregate, instant(10), instant(11), identifier).protection is ProtectionLevel.PROTECTED
    aggregate = aggregate.complete_segment(identifier).value
    with pytest.raises(ValueError, match="open segments"):
        assess_displacement(aggregate, instant(10), instant(11), identifier)


@pytest.mark.parametrize("level,reason", [
    (ProtectionLevel.REPLANNABLE, "REPLANNABLE_TRADEOFF"),
    (ProtectionLevel.FLEXIBLE, "FLEXIBLE_SLIP"),
])
def test_replannable_and_flexible_policy(level, reason):
    aggregate = TaskAggregate(Task(title="Work", protection=level))
    assert assess_displacement(aggregate, instant(10), instant(11)).reason_code == reason
    assert assess_displacement(aggregate, instant(10), instant(10)).confirmation_required is False
    assert assess_displacement(aggregate, instant(11), instant(10)).reason_code == "EARLIER_MOVE"


def test_preview_validates_input_and_segment_membership():
    aggregate = TaskAggregate(Task(title="Work"))
    with pytest.raises(ValueError, match="timezone"):
        assess_displacement(aggregate, datetime(2026, 10, 10), instant(11))
    with pytest.raises(ValueError, match="segment does not belong"):
        assess_displacement(aggregate, instant(10), instant(11), uuid4())
