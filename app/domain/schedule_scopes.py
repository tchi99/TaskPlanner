"""Real owner-scoped physical envelopes for fresh TP-026 installations."""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ScheduleScope:
    id: UUID
    owner_id: str
    name: str
    version: int = 1
    state: str = "ACTIVE"

    def __post_init__(self) -> None:
        if not self.owner_id or len(self.owner_id) > 128:
            raise ValueError("invalid scope owner")
        if not self.name.strip() or len(self.name) > 200:
            raise ValueError("scope name must have 1-200 characters")
        if self.version < 1 or self.state not in ("ACTIVE", "INACTIVE"):
            raise ValueError("invalid scope version or state")
