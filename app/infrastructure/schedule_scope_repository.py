"""TP-024A scope ownership, versioned temporal affiliation and command receipts."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.recurring_availability import RuleConflict
from app.domain.schedule_scopes import (
    ScheduleScope, ScopeAffiliation, compatibility_scope_id, effective_scope,
)
from app.infrastructure.models import (
    ScheduleScopeRecord, WorkTypeScopeAssignmentRecord, WorkTypeScopeVersionRecord,
    ScopeChangeCommandRecord, ScopeChangeAuditRecord,
)


class SqlScheduleScopeRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _domain(row: ScheduleScopeRecord) -> ScheduleScope:
        return ScheduleScope(
            id=UUID(row.id), owner_id=row.owner_id, name=row.name,
            version=row.version, state=row.state, is_compatibility=row.is_compatibility,
        )

    def compatibility(self, owner: str) -> ScheduleScope:
        return ScheduleScope(compatibility_scope_id(owner), owner,
                             "Héritage (compatibilité)", is_compatibility=True)

    def ensure_compatibility(self, owner: str) -> None:
        ident = str(compatibility_scope_id(owner))
        if self.session.get(ScheduleScopeRecord, ident) is None:
            self.session.add(ScheduleScopeRecord(
                id=ident, owner_id=owner, name="Héritage (compatibilité)",
                state="ACTIVE", version=1, is_compatibility=True,
            ))
            self.session.flush()

    def get(self, owner: str, ident: UUID) -> ScheduleScope | None:
        if ident == compatibility_scope_id(owner):
            row = self.session.get(ScheduleScopeRecord, str(ident))
            return self._domain(row) if row is not None else self.compatibility(owner)
        row = self.session.scalar(select(ScheduleScopeRecord).where(
            ScheduleScopeRecord.id == str(ident), ScheduleScopeRecord.owner_id == owner))
        return self._domain(row) if row else None

    def list_owner(self, owner: str) -> tuple[ScheduleScope, ...]:
        rows = self.session.scalars(select(ScheduleScopeRecord).where(
            ScheduleScopeRecord.owner_id == owner
        ).order_by(ScheduleScopeRecord.name, ScheduleScopeRecord.id)).all()
        values = [self._domain(row) for row in rows]
        if not any(row.is_compatibility for row in values):
            values.insert(0, self.compatibility(owner))
        return tuple(values)

    def add(self, value: ScheduleScope) -> None:
        self.session.add(ScheduleScopeRecord(
            id=str(value.id), owner_id=value.owner_id, name=value.name,
            state=value.state, version=value.version,
            is_compatibility=value.is_compatibility,
        ))
        self.session.flush()

    def save(self, value: ScheduleScope, expected_version: int) -> None:
        stmt = update(ScheduleScopeRecord).where(
            ScheduleScopeRecord.id == str(value.id),
            ScheduleScopeRecord.owner_id == value.owner_id,
            ScheduleScopeRecord.version == expected_version,
            ScheduleScopeRecord.is_compatibility.is_(False),
        ).values(name=value.name, state=value.state, version=expected_version + 1)
        if self.session.execute(stmt).rowcount != 1:
            raise RuleConflict("scope version changed or scope is immutable")
        self.session.flush()

    def affiliations(self, owner: str) -> tuple[ScopeAffiliation, ...]:
        rows = self.session.scalars(select(WorkTypeScopeAssignmentRecord).where(
            WorkTypeScopeAssignmentRecord.owner_id == owner
        ).order_by(WorkTypeScopeAssignmentRecord.work_type_id,
                   WorkTypeScopeAssignmentRecord.effective_from,
                   WorkTypeScopeAssignmentRecord.version)).all()
        return tuple(ScopeAffiliation(
            UUID(row.work_type_id), UUID(row.scope_id), owner,
            row.effective_from, row.version,
        ) for row in rows)

    def versions(self, owner: str) -> dict[str, int]:
        rows = self.session.scalars(select(WorkTypeScopeVersionRecord).where(
            WorkTypeScopeVersionRecord.owner_id == owner
        )).all()
        return {row.work_type_id: row.version for row in rows}

    def attach(self, owner: str, work_type_id: UUID, scope_id: UUID,
               effective_from: date, expected_version: int) -> ScopeAffiliation:
        if expected_version < 0:
            raise ValueError("invalid expected affiliation version")
        row = self.session.get(WorkTypeScopeVersionRecord, (owner, str(work_type_id)))
        if row is None:
            if expected_version != 0:
                raise RuleConflict("affiliation version changed; preview again")
            self.session.add(WorkTypeScopeVersionRecord(
                owner_id=owner, work_type_id=str(work_type_id), version=1))
        else:
            stmt = update(WorkTypeScopeVersionRecord).where(
                WorkTypeScopeVersionRecord.owner_id == owner,
                WorkTypeScopeVersionRecord.work_type_id == str(work_type_id),
                WorkTypeScopeVersionRecord.version == expected_version,
            ).values(version=expected_version + 1)
            if self.session.execute(stmt).rowcount != 1:
                raise RuleConflict("affiliation version changed; preview again")
        value = ScopeAffiliation(work_type_id, scope_id, owner,
                                 effective_from, expected_version + 1)
        self.session.add(WorkTypeScopeAssignmentRecord(
            id=str(uuid4()), owner_id=owner, work_type_id=str(work_type_id),
            scope_id=str(scope_id), effective_from=effective_from,
            version=value.version, recorded_at=datetime.now(timezone.utc),
        ))
        self.session.flush()
        return value

    def command(self, owner: str, ident: UUID) -> ScopeChangeCommandRecord | None:
        return self.session.get(ScopeChangeCommandRecord, (owner, str(ident)))

    def receipt(self, owner: str, ident: UUID, payload_hash: str, result: dict) -> None:
        self.session.add(ScopeChangeCommandRecord(
            owner_id=owner, command_id=str(ident), payload_hash=payload_hash,
            result=result, recorded_at=datetime.now(timezone.utc),
        ))
        self.session.flush()

    def audit(self, owner: str, kind: str, payload: dict, command_id: UUID | None) -> None:
        self.session.add(ScopeChangeAuditRecord(
            id=str(uuid4()), owner_id=owner, kind=kind,
            command_id=str(command_id) if command_id else None, payload=payload,
            recorded_at=datetime.now(timezone.utc),
        ))
        self.session.flush()
