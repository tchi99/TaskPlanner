"""Persistence adapter for TP-022A series; UoW owns the transaction."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleConflict, RuleKind, RuleRevision,
)
from app.infrastructure.models import (
    RecurringAvailabilityRevisionRecord, RecurringAvailabilityRuleRecord,
)


class SqlRecurringAvailabilityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _revision(row: RecurringAvailabilityRevisionRecord) -> RuleRevision:
        return RuleRevision(
            rule_id=UUID(row.rule_id), number=row.number,
            effective_from=row.effective_from, valid_until=row.valid_until,
            timezone_name=row.timezone_name, days_of_week=tuple(row.days_of_week),
            starts_at_local=row.starts_at_local, ends_at_local=row.ends_at_local,
            kind=RuleKind(row.kind), work_type_id=UUID(row.work_type_id) if row.work_type_id else None,
            mode=AvailabilityMode(row.mode) if row.mode else None,
            enabled=row.enabled, start_fold=row.start_fold, end_fold=row.end_fold,
            supersedes_future=row.supersedes_future,
        )

    def _assemble(self, row: RecurringAvailabilityRuleRecord) -> RecurringAvailabilityRule:
        records = self._session.scalars(
            select(RecurringAvailabilityRevisionRecord).where(
                RecurringAvailabilityRevisionRecord.rule_id == row.id
            ).order_by(RecurringAvailabilityRevisionRecord.number)
        ).all()
        return RecurringAvailabilityRule(
            UUID(row.id), row.owner_id, row.version,
            tuple(self._revision(value) for value in records),
        )

    def get(self, rule_id: UUID, owner_id: str) -> RecurringAvailabilityRule | None:
        row = self._session.scalar(select(RecurringAvailabilityRuleRecord).where(
            RecurringAvailabilityRuleRecord.id == str(rule_id),
            RecurringAvailabilityRuleRecord.owner_id == owner_id,
        ))
        return self._assemble(row) if row else None

    def list_owner(self, owner_id: str) -> list[RecurringAvailabilityRule]:
        rows = self._session.scalars(
            select(RecurringAvailabilityRuleRecord).where(
                RecurringAvailabilityRuleRecord.owner_id == owner_id
            ).order_by(RecurringAvailabilityRuleRecord.created_at,
                       RecurringAvailabilityRuleRecord.id)
        ).all()
        return [self._assemble(row) for row in rows]

    def _append(self, value: RuleRevision) -> None:
        self._session.add(RecurringAvailabilityRevisionRecord(
            id=str(uuid4()), rule_id=str(value.rule_id), number=value.number,
            effective_from=value.effective_from, valid_until=value.valid_until,
            timezone_name=value.timezone_name, days_of_week=list(value.days_of_week),
            starts_at_local=value.starts_at_local, ends_at_local=value.ends_at_local,
            kind=value.kind.value,
            work_type_id=str(value.work_type_id) if value.work_type_id else None,
            mode=value.mode.value if value.mode else None,
            enabled=value.enabled, start_fold=value.start_fold, end_fold=value.end_fold,
            supersedes_future=value.supersedes_future,
            recorded_at=datetime.now(timezone.utc),
        ))

    def add(self, value: RecurringAvailabilityRule) -> None:
        self._session.add(RecurringAvailabilityRuleRecord(
            id=str(value.id), owner_id=value.owner_id, version=1,
            created_at=datetime.now(timezone.utc),
        ))
        # No ORM relationship links the two records: make the parent row
        # visible to the FK constraint before inserting its first revision.
        # Both flushes remain inside the caller's atomic UnitOfWork.
        self._session.flush()
        self._append(value.revisions[0])
        self._session.flush()

    def append_revision(self, value: RuleRevision, *, expected_version: int) -> None:
        # Conditional SQL update is the concurrency boundary even if two
        # independent sessions both read the same version.
        result = self._session.execute(
            update(RecurringAvailabilityRuleRecord).where(
                RecurringAvailabilityRuleRecord.id == str(value.rule_id),
                RecurringAvailabilityRuleRecord.version == expected_version,
            ).values(version=expected_version + 1)
        )
        if result.rowcount != 1:
            raise RuleConflict("recurring rule changed; reload before updating")
        self._append(value)
        self._session.flush()
