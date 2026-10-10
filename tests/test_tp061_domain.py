"""Domain contract for explicit weekly choices."""
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.domain.weekly import WeeklyAction, WeeklyDecision, WeeklySubject


WEEK = date(2026, 10, 5)


def decision(*, action=WeeklyAction.RECIRCULATE, review_on=None,
             week_start=WEEK, timezone_name="America/Toronto", revision=1):
    return WeeklyDecision(
        week_start=week_start, timezone_name=timezone_name,
        subject_kind=WeeklySubject.TASK, subject_id=uuid4(),
        action=action, review_on=review_on,
        decided_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        revision=revision,
    )


def test_weekly_choice_has_no_implicit_review_date():
    item = decision()
    assert item.action is WeeklyAction.RECIRCULATE
    assert item.review_on is None


@pytest.mark.parametrize("action", [WeeklyAction.POSTPONE, WeeklyAction.REVIEW_LATER])
def test_future_followup_required_for_deferral(action):
    with pytest.raises(ValueError, match="requires"):
        decision(action=action)
    with pytest.raises(ValueError, match="after"):
        decision(action=action, review_on=date(2026, 10, 10))
    assert decision(action=action, review_on=date(2026, 10, 12)).review_on == date(2026, 10, 12)


def test_invalid_week_timezone_revision_and_time_are_rejected():
    with pytest.raises(ValueError, match="Monday"):
        decision(week_start=date(2026, 10, 6))
    with pytest.raises(ValueError, match="timezone"):
        decision(timezone_name="Bad/Zone")
    with pytest.raises(ValueError, match="revision"):
        decision(revision=0)
    with pytest.raises(ValueError, match="aware"):
        WeeklyDecision(
            WEEK, "UTC", WeeklySubject.PROJECT, uuid4(),
            WeeklyAction.DELEGATE, None, datetime(2026, 10, 10),
        )
