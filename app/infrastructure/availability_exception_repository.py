"""Persistent exceptions with compare-and-swap and owner-scoped reads."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.recurring_availability import AvailabilityMode, RuleConflict, RuleKind
from app.infrastructure.models import AvailabilityExceptionRecord


class SqlAvailabilityExceptionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _domain(record: AvailabilityExceptionRecord) -> AvailabilityException:
        return AvailabilityException(
            id=UUID(record.id), owner_id=record.owner_id, version=record.version,
            action=ExceptionAction(record.action),
            rule_id=UUID(record.rule_id) if record.rule_id else None,
            original_local_date=record.original_local_date,
            starts_at=datetime.fromisoformat(record.starts_at) if record.starts_at else None,
            ends_at=datetime.fromisoformat(record.ends_at) if record.ends_at else None,
            timezone_name=record.timezone_name,
            kind=RuleKind(record.kind) if record.kind else None,
            work_type_id=UUID(record.work_type_id) if record.work_type_id else None,
            mode=AvailabilityMode(record.mode) if record.mode else None,
            enabled=record.enabled, reason=record.reason,
            scope_id=UUID(record.scope_id) if record.scope_id else None,
        )

    @staticmethod
    def _values(value: AvailabilityException) -> dict:
        return {
            "action": value.action.value,
            "rule_id": str(value.rule_id) if value.rule_id else None,
            "original_local_date": value.original_local_date,
            "starts_at": value.starts_at.isoformat() if value.starts_at else None,
            "ends_at": value.ends_at.isoformat() if value.ends_at else None,
            "timezone_name": value.timezone_name,
            "kind": value.kind.value if value.kind else None,
            "work_type_id": str(value.work_type_id) if value.work_type_id else None,
            "mode": value.mode.value if value.mode else None,
            "enabled": value.enabled, "reason": value.reason,
            "scope_id": str(value.scope_id) if value.scope_id else None,
            "updated_at": datetime.now(timezone.utc),
        }

    def get(self, exception_id: UUID, owner_id: str) -> AvailabilityException | None:
        record = self._session.scalar(select(AvailabilityExceptionRecord).where(
            AvailabilityExceptionRecord.id == str(exception_id),
            AvailabilityExceptionRecord.owner_id == owner_id,
        ))
        return self._domain(record) if record else None

    def list_owner(self, owner_id: str) -> list[AvailabilityException]:
        records = self._session.scalars(select(AvailabilityExceptionRecord).where(
            AvailabilityExceptionRecord.owner_id == owner_id
        ).order_by(AvailabilityExceptionRecord.id)).all()
        return [self._domain(record) for record in records]

    def add(self, value: AvailabilityException) -> None:
        self._session.add(AvailabilityExceptionRecord(
            id=str(value.id), owner_id=value.owner_id, version=value.version,
            **self._values(value),
        ))
        self._session.flush()

    def save(self, value: AvailabilityException, *, expected_version: int) -> None:
        change = self._session.execute(update(AvailabilityExceptionRecord).where(
            AvailabilityExceptionRecord.id == str(value.id),
            AvailabilityExceptionRecord.owner_id == value.owner_id,
            AvailabilityExceptionRecord.version == expected_version,
        ).values(version=expected_version + 1, **self._values(value)))
        if change.rowcount != 1:
            raise RuleConflict("availability exception changed; reload and preview again")
        self._session.flush()
