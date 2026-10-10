"""TP-071: explicit intervals never include pauses or inactive gaps."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.work_sessions import SessionConflict, SessionStatus, WorkSession


START = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)


def test_elapsed_gap_does_not_inflate_active_time():
    value = WorkSession.start(uuid4(), None, START, None, 20, planned_minutes=10)
    assert value.status is SessionStatus.ACTIVE
    assert value.observed_seconds(START + timedelta(minutes=5)) == 300
    assert value.guardrail(START + timedelta(minutes=5)) is None
    value = value.pause(START + timedelta(minutes=5))
    assert value.active_seconds == 300
    assert value.interruptions == 1
    assert value.observed_seconds(START + timedelta(hours=2)) == 300
    assert value.guardrail(START + timedelta(hours=2)) is None
    value = value.resume(START + timedelta(hours=2))
    assert value.guardrail(START + timedelta(hours=2, minutes=5)) == "PLANNED_BLOCK_REACHED"
    value = value.finish(START + timedelta(hours=2, minutes=7))
    assert value.active_seconds == 720
    assert value.interruptions == 1
    assert value.status is SessionStatus.FINISHED
    assert value.finished_at == START + timedelta(hours=2, minutes=7)
    with pytest.raises(SessionConflict):
        value.resume(START + timedelta(hours=3))
    with pytest.raises(SessionConflict):
        value.finish(START + timedelta(hours=3))


def test_clock_and_transition_validation():
    value = WorkSession.start(uuid4(), None, START, None, None)
    with pytest.raises(ValueError, match="clock"):
        value.pause(START - timedelta(seconds=1))
    with pytest.raises(SessionConflict):
        value.resume(START + timedelta(seconds=1))
    paused = value.pause(START + timedelta(seconds=2))
    with pytest.raises(SessionConflict):
        paused.pause(START + timedelta(seconds=3))
    with pytest.raises(ValueError, match="timezone"):
        paused.resume(datetime(2026, 10, 10, 13, 10))
    with pytest.raises(ValueError, match="positive"):
        WorkSession.start(uuid4(), None, START, None, 0)
