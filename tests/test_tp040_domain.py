from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domain.calendar import CalendarCommitment, calculate_calendar_capacity
from app.domain.capacity import AvailabilityBlock


WEEK = date(2026, 10, 5)


def dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(
        f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00-04:00"
    )


def event(first: datetime, last: datetime, eid="one") -> CalendarCommitment:
    return CalendarCommitment("primary", eid, "Busy", first, last)


def block(first: datetime, last: datetime, work_type_id=None) -> AvailabilityBlock:
    return AvailabilityBlock(
        week_start=WEEK, starts_at=first, ends_at=last,
        work_type_id=work_type_id,
    )


def test_intersection_union_clip_and_separate_buckets():
    focus = uuid4()
    blocks = [
        block(dt(5, 9), dt(5, 12), focus),
        block(dt(5, 13), dt(5, 14)),
    ]
    events = [
        event(dt(5, 8), dt(5, 10), "early"),
        event(dt(5, 9, 30), dt(5, 11), "overlap"),
        event(dt(5, 10), dt(5, 11), "duplicate"),
        event(dt(5, 13, 15), dt(5, 13, 45), "lunch"),
        event(dt(5, 14), dt(5, 15), "outside"),
    ]
    result = calculate_calendar_capacity(WEEK, blocks, events)
    assert result.manual_available_minutes == 240
    assert result.occupied_minutes == 150
    assert result.remaining_minutes == 90
    assert {item.work_type_id: item.remaining_minutes for item in result.by_work_type} == {
        focus: 60, None: 30,
    }


def test_no_manual_blocks_means_no_imaginary_capacity():
    result = calculate_calendar_capacity(WEEK, [], [event(dt(5, 9), dt(5, 10))])
    assert result.manual_available_minutes == 0
    assert result.remaining_minutes == 0
    assert result.by_work_type == ()


def test_fractional_minute_is_conservatively_occupied():
    tiny = event(
        datetime.fromisoformat("2026-10-05T09:00:30-04:00"),
        datetime.fromisoformat("2026-10-05T09:00:45-04:00"),
    )
    result = calculate_calendar_capacity(
        WEEK, [block(dt(5, 9), dt(5, 10))], [tiny]
    )
    assert result.occupied_minutes == 1
    assert result.remaining_minutes == 59


def test_timezone_offsets_compare_actual_instants_at_dst():
    week = date(2026, 10, 26)
    availability = AvailabilityBlock(
        week_start=week,
        starts_at=datetime.fromisoformat("2026-11-01T00:00:00-04:00"),
        ends_at=datetime.fromisoformat("2026-11-01T03:00:00-05:00"),
    )
    busy = event(
        datetime.fromisoformat("2026-11-01T01:30:00-04:00"),
        datetime.fromisoformat("2026-11-01T01:30:00-05:00"),
    )
    result = calculate_calendar_capacity(week, [availability], [busy])
    assert result.manual_available_minutes == 240
    assert result.occupied_minutes == 60
    assert result.remaining_minutes == 180


def test_invalid_events_and_overlapping_manual_blocks_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        event(datetime(2026, 10, 5, 9), dt(5, 10))
    with pytest.raises(ValueError, match="follow"):
        event(dt(5, 11), dt(5, 10))
    with pytest.raises(ValueError, match="overlap"):
        calculate_calendar_capacity(
            WEEK,
            [block(dt(5, 9), dt(5, 11)), block(dt(5, 10), dt(5, 12))],
            [],
        )
