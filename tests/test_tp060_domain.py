"""Daily review decisions are explicit; missed interaction is not a failure."""
from datetime import date
from uuid import uuid4

import pytest

from app.domain.daily import (
    DailyFollowup, DailyReview, DailyState, RevisitReason, resurfaced,
)

DAY = date(2026, 10, 10)


def test_domain_rejects_invalid_followups_and_duplicate_selection():
    a = uuid4()
    with pytest.raises(ValueError, match="unique"):
        DailyReview(DAY, "UTC", (a, a))
    with pytest.raises(ValueError, match="timezone"):
        DailyReview(DAY, "Not/AZone", (a,))
    with pytest.raises(ValueError, match="after"):
        DailyReview(DAY, "UTC", (a,), state=DailyState.CLOSED,
                    followups=(DailyFollowup(a, DAY),))
    with pytest.raises(ValueError, match="selected"):
        DailyReview(DAY, "UTC", (a,), state=DailyState.CLOSED,
                    followups=(DailyFollowup(uuid4(), date(2026, 10, 11)),))
    with pytest.raises(ValueError, match="open"):
        DailyReview(DAY, "UTC", (a,), followups=(
            DailyFollowup(a, date(2026, 10, 11)),))


def test_resurfacing_is_due_only_and_latest_decision_wins():
    a, b, c = uuid4(), uuid4(), uuid4()
    old = DailyReview(date(2026, 10, 6), "UTC", (a, b))
    closed = DailyReview(
        date(2026, 10, 7), "UTC", (a, c),
        state=DailyState.CLOSED, followups=(
            DailyFollowup(a, date(2026, 10, 12)),
            DailyFollowup(c, date(2026, 10, 9)),
        ),
    )
    due = resurfaced([closed, old], DAY, {a, b, c}, set())
    assert {item.task_id: item.reason for item in due} == {
        b: RevisitReason.UNFINISHED_DAY,
        c: RevisitReason.REVIEW_DUE,
    }
    assert resurfaced([closed, old], date(2026, 10, 12),
                      {a, b, c}, {a, b}) == (
        next(item for item in resurfaced([closed, old], date(2026, 10, 12),
                                        {a, b, c}, set()) if item.task_id == c),
    )
    assert resurfaced([closed, old], DAY, set(), set()) == ()
