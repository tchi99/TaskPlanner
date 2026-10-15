"""Owner-scoped idempotency receipts live in the same planning transaction."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.infrastructure.models import WeeklyScheduleCommandRecord


class SqlWeeklyScheduleCommandRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, owner_id: str, command_id: UUID) -> WeeklyScheduleCommandRecord | None:
        return self.session.get(WeeklyScheduleCommandRecord, (owner_id, str(command_id)))

    def add(self, owner_id: str, command_id: UUID, payload_hash: str, result: dict) -> None:
        self.session.add(WeeklyScheduleCommandRecord(
            owner_id=owner_id, command_id=str(command_id),
            payload_hash=payload_hash, result=result, created_at=datetime.now(timezone.utc),
        ))
