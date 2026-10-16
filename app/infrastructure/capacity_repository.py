"""SQLAlchemy adapter for manually declared weekly availability."""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.capacity import AvailabilityBlock
from app.infrastructure.models import AvailabilityBlockRecord


class SqlAvailabilityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _domain(record: AvailabilityBlockRecord) -> AvailabilityBlock:
        return AvailabilityBlock(
            id=UUID(record.id),
            week_start=record.week_start,
            starts_at=datetime.fromisoformat(record.starts_at),
            ends_at=datetime.fromisoformat(record.ends_at),
            work_type_id=UUID(record.work_type_id) if record.work_type_id else None,
            scope_id=UUID(record.scope_id) if record.scope_id else None,
        )

    def add(self, block: AvailabilityBlock) -> AvailabilityBlock:
        self._session.add(AvailabilityBlockRecord(
            id=str(block.id),
            week_start=block.week_start,
            starts_at=block.starts_at.isoformat(),
            ends_at=block.ends_at.isoformat(),
            work_type_id=str(block.work_type_id) if block.work_type_id else None,
            scope_id=str(block.scope_id) if block.scope_id else None,
        ))
        return block

    def get(self, block_id: UUID) -> AvailabilityBlock | None:
        record = self._session.get(AvailabilityBlockRecord, str(block_id))
        return self._domain(record) if record else None

    def list_week(self, week_start: date) -> list[AvailabilityBlock]:
        records = self._session.scalars(
            select(AvailabilityBlockRecord)
            .where(AvailabilityBlockRecord.week_start == week_start)
            .order_by(AvailabilityBlockRecord.starts_at, AvailabilityBlockRecord.id)
        ).all()
        return [self._domain(record) for record in records]

    def delete(self, block_id: UUID) -> None:
        record = self._session.get(AvailabilityBlockRecord, str(block_id))
        if record is None:
            raise LookupError("availability block not found")
        self._session.delete(record)
