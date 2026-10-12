"""Local-only confirmed time-block persistence (not Google Calendar events)."""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.time_blocks import ConfirmedTimeBlock
from app.infrastructure.models import ConfirmedTimeBlockRecord


class SqlConfirmedTimeBlockRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_week(self, week_start: date) -> list[ConfirmedTimeBlock]:
        records = self.session.scalars(
            select(ConfirmedTimeBlockRecord)
            .where(ConfirmedTimeBlockRecord.week_start == week_start,
                   ConfirmedTimeBlockRecord.status == "CONFIRMED")
            .order_by(ConfirmedTimeBlockRecord.starts_at, ConfirmedTimeBlockRecord.id)
        ).all()
        return [self._to_domain(row) for row in records]

    @staticmethod
    def _to_domain(row: ConfirmedTimeBlockRecord) -> ConfirmedTimeBlock:
        return ConfirmedTimeBlock(
            id=UUID(row.id), week_start=row.week_start,
            task_id=UUID(row.task_id),
            segment_id=UUID(row.segment_id) if row.segment_id else None,
            work_type_id=UUID(row.work_type_id) if row.work_type_id else None,
            starts_at=datetime.fromisoformat(row.starts_at),
            ends_at=datetime.fromisoformat(row.ends_at),
            transferred_from=(UUID(row.transferred_from_work_type_id)
                              if row.transferred_from_work_type_id else None),
            status=row.status, revision=row.revision,
        )

    def get(self, booking_id: UUID) -> ConfirmedTimeBlock | None:
        row = self.session.get(ConfirmedTimeBlockRecord, str(booking_id))
        return self._to_domain(row) if row is not None else None

    def revise(self, booking: ConfirmedTimeBlock, *, status: str) -> None:
        statement = update(ConfirmedTimeBlockRecord).where(
            ConfirmedTimeBlockRecord.id == str(booking.id),
            ConfirmedTimeBlockRecord.status == "CONFIRMED",
            ConfirmedTimeBlockRecord.revision == booking.revision,
        ).values(status=status, revision=booking.revision + 1)
        if self.session.execute(statement).rowcount != 1:
            raise ValueError("booking changed before resolution")

    def add(self, block: ConfirmedTimeBlock) -> None:
        self.session.add(ConfirmedTimeBlockRecord(
            id=str(block.id), week_start=block.week_start, task_id=str(block.task_id),
            segment_id=str(block.segment_id) if block.segment_id else None,
            work_type_id=str(block.work_type_id) if block.work_type_id else None,
            starts_at=block.starts_at.isoformat(), ends_at=block.ends_at.isoformat(),
            status=block.status, revision=block.revision,
            transferred_from_work_type_id=(str(block.transferred_from)
                                           if block.transferred_from else None),
        ))
