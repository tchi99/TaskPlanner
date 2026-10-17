"""TP-025A: owner-scoped, CAS-versioned and append-only eligibility storage.

Callers own a planning UnitOfWork and its transaction. No web/API mutation is
exposed until a preview/confirm command is designed in the later tranche.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.eligibility import (
    EligibilityAction, EligibilityConflict, EligibilityException,
    EligibilityRevision, EligibilitySeries,
)
from app.infrastructure.models import (
    EligibilitySeriesRecord, EligibilityRevisionRecord,
    EligibilityExceptionRecord, EligibilityExceptionRevisionRecord,
)


class SqlEligibilityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _revision(row: EligibilityRevisionRecord) -> EligibilityRevision:
        return EligibilityRevision(
            UUID(row.series_id), row.number, row.effective_from, row.valid_until,
            row.timezone_name, tuple(row.days_of_week),
            row.starts_at_local, row.ends_at_local, row.priority_rank,
            row.enabled, row.start_fold, row.end_fold, row.supersedes_future,
        )

    def _assemble(self, row: EligibilitySeriesRecord) -> EligibilitySeries:
        revisions = self._session.scalars(
            select(EligibilityRevisionRecord).where(
                EligibilityRevisionRecord.series_id == row.id,
            ).order_by(EligibilityRevisionRecord.number)
        ).all()
        return EligibilitySeries(
            UUID(row.id), row.owner_id, UUID(row.scope_id),
            UUID(row.work_type_id), row.version,
            tuple(self._revision(value) for value in revisions),
        )

    def get(self, series_id: UUID, owner_id: str) -> EligibilitySeries | None:
        row = self._session.scalar(select(EligibilitySeriesRecord).where(
            EligibilitySeriesRecord.id == str(series_id),
            EligibilitySeriesRecord.owner_id == owner_id,
        ))
        return self._assemble(row) if row else None

    def list_owner(self, owner_id: str) -> list[EligibilitySeries]:
        rows = self._session.scalars(select(EligibilitySeriesRecord).where(
            EligibilitySeriesRecord.owner_id == owner_id,
        ).order_by(EligibilitySeriesRecord.created_at, EligibilitySeriesRecord.id)).all()
        return [self._assemble(row) for row in rows]

    def _append(self, revision: EligibilityRevision) -> None:
        self._session.add(EligibilityRevisionRecord(
            id=str(uuid4()), series_id=str(revision.series_id), number=revision.number,
            effective_from=revision.effective_from, valid_until=revision.valid_until,
            timezone_name=revision.timezone_name, days_of_week=list(revision.days_of_week),
            starts_at_local=revision.starts_at_local, ends_at_local=revision.ends_at_local,
            priority_rank=revision.priority_rank, enabled=revision.enabled,
            start_fold=revision.start_fold, end_fold=revision.end_fold,
            supersedes_future=revision.supersedes_future,
            recorded_at=datetime.now(timezone.utc),
        ))

    def add(self, value: EligibilitySeries) -> None:
        if value.version != 1:
            raise ValueError("new eligibility series must start at version 1")
        self._session.add(EligibilitySeriesRecord(
            id=str(value.id), owner_id=value.owner_id, scope_id=str(value.scope_id),
            work_type_id=str(value.work_type_id), version=1,
            created_at=datetime.now(timezone.utc),
        ))
        self._session.flush()  # Parent FK exists inside the same transaction.
        self._append(value.revisions[0])
        self._session.flush()

    def append_revision(self, owner_id: str, revision: EligibilityRevision,
                        *, expected_version: int) -> None:
        if revision.number != expected_version + 1:
            raise ValueError("revision number must follow expected version")
        result = self._session.execute(
            update(EligibilitySeriesRecord).where(
                EligibilitySeriesRecord.id == str(revision.series_id),
                EligibilitySeriesRecord.owner_id == owner_id,
                EligibilitySeriesRecord.version == expected_version,
            ).values(version=expected_version + 1)
        )
        if result.rowcount != 1:
            raise EligibilityConflict("eligibility series changed; preview again")
        self._append(revision)
        self._session.flush()

    @staticmethod
    def _exception_revision(row: EligibilityExceptionRecord,
                            revision: EligibilityExceptionRevisionRecord) -> EligibilityException:
        return EligibilityException(
            id=UUID(row.id), owner_id=row.owner_id, series_id=UUID(row.series_id),
            original_local_date=row.original_local_date, version=row.version,
            action=EligibilityAction(revision.action),
            timezone_name=revision.timezone_name,
            starts_at=revision.starts_at, ends_at=revision.ends_at,
            enabled=revision.enabled,
        )

    def get_exception(self, exception_id: UUID, owner_id: str) -> EligibilityException | None:
        row = self._session.scalar(select(EligibilityExceptionRecord).where(
            EligibilityExceptionRecord.id == str(exception_id),
            EligibilityExceptionRecord.owner_id == owner_id,
        ))
        if row is None:
            return None
        rev = self._session.scalar(select(EligibilityExceptionRevisionRecord).where(
            EligibilityExceptionRevisionRecord.exception_id == row.id,
            EligibilityExceptionRevisionRecord.number == row.version,
        ))
        assert rev is not None
        return self._exception_revision(row, rev)

    def list_exceptions(self, owner_id: str) -> list[EligibilityException]:
        rows = self._session.scalars(select(EligibilityExceptionRecord).where(
            EligibilityExceptionRecord.owner_id == owner_id,
        ).order_by(EligibilityExceptionRecord.id)).all()
        return [self.get_exception(UUID(row.id), owner_id) for row in rows]

    def _append_exception(self, value: EligibilityException) -> None:
        self._session.add(EligibilityExceptionRevisionRecord(
            id=str(uuid4()), exception_id=str(value.id), number=value.version,
            action=value.action.value, timezone_name=value.timezone_name,
            starts_at=value.starts_at, ends_at=value.ends_at, enabled=value.enabled,
            recorded_at=datetime.now(timezone.utc),
        ))
        self._session.flush()

    def add_exception(self, value: EligibilityException) -> None:
        if value.version != 1:
            raise ValueError("new eligibility exception must start at version 1")
        if self.get(value.series_id, value.owner_id) is None:
            raise LookupError("eligibility series not owned by requester")
        self._session.add(EligibilityExceptionRecord(
            id=str(value.id), owner_id=value.owner_id, series_id=str(value.series_id),
            original_local_date=value.original_local_date, version=1,
            created_at=datetime.now(timezone.utc),
        ))
        self._session.flush()
        self._append_exception(value)

    def append_exception(self, value: EligibilityException,
                         *, expected_version: int) -> None:
        if value.version != expected_version + 1:
            raise ValueError("exception revision must follow expected version")
        result = self._session.execute(
            update(EligibilityExceptionRecord).where(
                EligibilityExceptionRecord.id == str(value.id),
                EligibilityExceptionRecord.owner_id == value.owner_id,
                EligibilityExceptionRecord.series_id == str(value.series_id),
                EligibilityExceptionRecord.original_local_date == value.original_local_date,
                EligibilityExceptionRecord.version == expected_version,
            ).values(version=value.version)
        )
        if result.rowcount != 1:
            raise EligibilityConflict("eligibility exception changed; preview again")
        self._append_exception(value)
