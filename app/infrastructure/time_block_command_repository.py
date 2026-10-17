"""Atomic idempotency receipt for TP-025B local confirmation."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.infrastructure.models import TimeBlockCommandRecord


class SqlTimeBlockCommandRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, owner_id: str, command_id: UUID) -> TimeBlockCommandRecord | None:
        return self.session.get(TimeBlockCommandRecord, (owner_id, str(command_id)))

    def add(self, owner_id: str, command_id: UUID, payload_hash: str, result: dict) -> None:
        self.session.add(TimeBlockCommandRecord(
            owner_id=owner_id, command_id=str(command_id),
            payload_hash=payload_hash, result=result,
            created_at=datetime.now(timezone.utc),
        ))
