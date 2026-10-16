"""TP-024A: two-level scope/leaf identities and dated affiliations.

Names are presentation only. NULL work type belongs to one scope, never globally.
A missing attachment means the explicit legacy compatibility scope, not a guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, NAMESPACE_URL, uuid5


def compatibility_scope_id(owner_id: str) -> UUID:
    if not owner_id or len(owner_id) > 128:
        raise ValueError("invalid scope owner")
    return uuid5(NAMESPACE_URL, "taskplanner:compatibility-scope:" + owner_id)


@dataclass(frozen=True, slots=True)
class ScheduleScope:
    id: UUID
    owner_id: str
    name: str
    version: int = 1
    state: str = "ACTIVE"
    is_compatibility: bool = False

    def __post_init__(self):
        if not self.owner_id or len(self.owner_id) > 128:
            raise ValueError("invalid scope owner")
        if not self.name.strip() or len(self.name) > 200:
            raise ValueError("scope name must have 1-200 characters")
        if self.version < 1 or self.state not in ("ACTIVE", "INACTIVE"):
            raise ValueError("invalid scope version or state")
        if self.is_compatibility and self.id != compatibility_scope_id(self.owner_id):
            raise ValueError("legacy scope identity must be deterministic")


@dataclass(frozen=True, slots=True)
class ScopeAffiliation:
    work_type_id: UUID
    scope_id: UUID
    owner_id: str
    effective_from: date
    version: int

    def __post_init__(self):
        if not self.owner_id or self.version < 1:
            raise ValueError("invalid affiliation version or owner")


def effective_scope(
    work_type_id: UUID, civil_date: date, affiliations: tuple[ScopeAffiliation, ...],
    compatibility_id: UUID,
) -> UUID:
    matching = [a for a in affiliations if a.work_type_id == work_type_id
                and a.effective_from <= civil_date]
    return max(matching, key=lambda a: (a.effective_from, a.version)).scope_id if matching else compatibility_id
