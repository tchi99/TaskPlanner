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


# Projection adapter: affiliations are computed from permanent WorkType.scope_id.
# This structure is never persisted or edited as dated history in TP-026.
from datetime import date


@dataclass(frozen=True, slots=True)
class ScopeAffiliation:
    work_type_id: UUID
    scope_id: UUID
    owner_id: str
    effective_from: date = date.min
    version: int = 1


def compatibility_scope_id(owner_id: str) -> UUID:
    """Legacy-only sentinel, never a real parent or source of physical time."""
    return UUID(int=0)


def effective_scope(work_type_id: UUID, civil_date: date,
                    affiliations: tuple[ScopeAffiliation, ...],
                    compatibility_id: UUID | None = None) -> UUID:
    matches = {item.scope_id for item in affiliations
               if item.work_type_id == work_type_id}
    if len(matches) != 1:
        raise ValueError("work type lacks a real parent; classify explicitly")
    return next(iter(matches))
