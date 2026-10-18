"""Owner-scoped physical schedule parents: no synthetic compatibility identity."""
from __future__ import annotations
from datetime import date, datetime, timezone
import json
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.recurring_availability import RuleConflict
from app.domain.schedule_scopes import ScheduleScope, ScopeAffiliation
from app.infrastructure.models import (
    ScheduleScopeRecord, ScopeChangeCommandRecord, ScopeChangeAuditRecord,
    WorkTypeRecord,
)


class SqlScheduleScopeRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _domain(row: ScheduleScopeRecord) -> ScheduleScope:
        return ScheduleScope(id=UUID(row.id), owner_id=row.owner_id, name=row.name,
                             version=row.version, state=row.state)

    def get(self, owner: str, ident: UUID) -> ScheduleScope | None:
        row = self.session.scalar(select(ScheduleScopeRecord).where(
            ScheduleScopeRecord.id == str(ident), ScheduleScopeRecord.owner_id == owner))
        return self._domain(row) if row else None

    def list_owner(self, owner: str) -> tuple[ScheduleScope, ...]:
        rows = self.session.scalars(select(ScheduleScopeRecord).where(
            ScheduleScopeRecord.owner_id == owner
        ).order_by(ScheduleScopeRecord.name, ScheduleScopeRecord.id)).all()
        return tuple(self._domain(row) for row in rows)

    def add(self, value: ScheduleScope) -> None:
        self.session.add(ScheduleScopeRecord(
            id=str(value.id), owner_id=value.owner_id, name=value.name,
            state=value.state, version=value.version,
        ))
        self.session.flush()

    def save(self, value: ScheduleScope, expected_version: int) -> None:
        stmt = update(ScheduleScopeRecord).where(
            ScheduleScopeRecord.id == str(value.id),
            ScheduleScopeRecord.owner_id == value.owner_id,
            ScheduleScopeRecord.version == expected_version,
        ).values(name=value.name, state=value.state, version=expected_version + 1)
        if self.session.execute(stmt).rowcount != 1:
            raise RuleConflict("scope version changed")
        self.session.flush()

    def affiliations(self, owner: str) -> tuple[ScopeAffiliation, ...]:
        # Read-only projection from permanent WorkType parent; no dated records.
        rows = self.session.execute(select(WorkTypeRecord.id, WorkTypeRecord.scope_id)
            .join(ScheduleScopeRecord, WorkTypeRecord.scope_id == ScheduleScopeRecord.id)
            .where(ScheduleScopeRecord.owner_id == owner)).all()
        return tuple(ScopeAffiliation(UUID(ident), UUID(scope), owner)
                     for ident, scope in rows)

    def versions(self, owner: str) -> dict[str, int]:
        rows = self.session.execute(select(WorkTypeRecord.id, WorkTypeRecord.version)
            .join(ScheduleScopeRecord, WorkTypeRecord.scope_id == ScheduleScopeRecord.id)
            .where(ScheduleScopeRecord.owner_id == owner)).all()
        return {ident: version for ident, version in rows}

    def ensure_compatibility(self, owner: str) -> None:
        raise ValueError("synthetic compatibility parents are not supported")

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
            command_id=str(command_id) if command_id else None,
            payload=json.loads(json.dumps(payload, default=str)),
            recorded_at=datetime.now(timezone.utc),
        ))
        self.session.flush()
