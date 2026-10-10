"""Persistence for explicit weekly review intentions (not task changes)."""
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.weekly import WeeklyAction, WeeklyDecision, WeeklySubject
from app.infrastructure.models import WeeklyDecisionRecord


def _decode(record: WeeklyDecisionRecord) -> WeeklyDecision:
    return WeeklyDecision(
        week_start=record.week_start, timezone_name=record.timezone_name,
        subject_kind=WeeklySubject(record.subject_kind), subject_id=UUID(record.subject_id),
        action=WeeklyAction(record.action), review_on=record.review_on,
        decided_at=record.decided_at, revision=record.revision,
    )


class SqlWeeklyReviewRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, week_start: date, timezone_name: str,
            subject_kind: WeeklySubject, subject_id: UUID) -> WeeklyDecision | None:
        row = self.session.get(
            WeeklyDecisionRecord,
            (week_start, timezone_name, subject_kind.value, str(subject_id)),
        )
        return _decode(row) if row else None

    def list_week(self, week_start: date, timezone_name: str) -> list[WeeklyDecision]:
        rows = self.session.scalars(
            select(WeeklyDecisionRecord)
            .where(WeeklyDecisionRecord.week_start == week_start,
                   WeeklyDecisionRecord.timezone_name == timezone_name)
            .order_by(WeeklyDecisionRecord.subject_kind, WeeklyDecisionRecord.subject_id)
        ).all()
        return [_decode(row) for row in rows]

    def save(self, decision: WeeklyDecision) -> None:
        key = (decision.week_start, decision.timezone_name,
               decision.subject_kind.value, str(decision.subject_id))
        row = self.session.get(WeeklyDecisionRecord, key)
        if row is None:
            row = WeeklyDecisionRecord(
                week_start=decision.week_start,
                timezone_name=decision.timezone_name,
                subject_kind=decision.subject_kind.value,
                subject_id=str(decision.subject_id),
            )
            self.session.add(row)
        row.action = decision.action.value
        row.review_on = decision.review_on
        row.decided_at = decision.decided_at
        row.revision = decision.revision
