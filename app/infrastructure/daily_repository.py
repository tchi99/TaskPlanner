"""Local daily reviews, separate from business task status and calendars."""
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.daily import DailyFollowup, DailyReview, DailyState
from app.infrastructure.models import DailyReviewRecord


def _decode(row: DailyReviewRecord) -> DailyReview:
    return DailyReview(
        day=row.day, timezone_name=row.timezone_name,
        selected_task_ids=tuple(UUID(value) for value in row.selected_task_ids),
        state=DailyState(row.state), revision=row.revision,
        followups=tuple(DailyFollowup(UUID(value["task_id"]),
                                     date.fromisoformat(value["review_on"]))
                        for value in row.followups),
    )


class SqlDailyReviewRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, day: date, timezone_name: str) -> DailyReview | None:
        record = self.session.get(DailyReviewRecord, (day, timezone_name))
        return _decode(record) if record else None

    def list_before(self, day: date, timezone_name: str) -> list[DailyReview]:
        records = self.session.scalars(
            select(DailyReviewRecord)
            .where(DailyReviewRecord.day < day,
                   DailyReviewRecord.timezone_name == timezone_name)
            .order_by(DailyReviewRecord.day)
        ).all()
        return [_decode(record) for record in records]

    def save(self, review: DailyReview) -> None:
        record = self.session.get(DailyReviewRecord, (review.day, review.timezone_name))
        if record is None:
            record = DailyReviewRecord(day=review.day, timezone_name=review.timezone_name)
            self.session.add(record)
        record.selected_task_ids = [str(task_id) for task_id in review.selected_task_ids]
        record.state = review.state.value
        record.followups = [
            {"task_id": str(item.task_id), "review_on": item.review_on.isoformat()}
            for item in review.followups
        ]
        record.revision = review.revision
