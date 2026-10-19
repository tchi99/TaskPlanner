"""TP-026A: real owner-scoped parents, without dated affiliations or fallback."""
from __future__ import annotations
from dataclasses import asdict, replace
from uuid import UUID, uuid4

from app.application.uow import UnitOfWork
from app.domain.recurring_availability import RuleConflict
from app.domain.schedule_scopes import ScheduleScope


def _validate_name(name: str) -> str:
    if not name.strip() or len(name) > 200:
        raise ValueError("scope name must be 1-200 characters")
    return name.strip()


def list_scopes(uow: UnitOfWork, owner: str) -> dict:
    with uow:
        return {"scopes": [asdict(v) for v in uow.schedule_scopes.list_owner(owner)]}


def create_scope(uow: UnitOfWork, owner: str, name: str) -> ScheduleScope:
    name = _validate_name(name)
    with uow:
        uow.lock_planning()
        if any(s.name.casefold() == name.casefold()
               for s in uow.schedule_scopes.list_owner(owner)):
            raise RuleConflict("a scope with this name already exists")
        value = ScheduleScope(uuid4(), owner, name)
        uow.schedule_scopes.add(value)
        uow.schedule_scopes.audit(owner, "SCOPE_CREATED", asdict(value), None)
        uow.commit()
        return value


def update_scope(uow: UnitOfWork, owner: str, scope_id: UUID,
                 expected_version: int, name: str, state: str) -> ScheduleScope:
    name = _validate_name(name)
    with uow:
        uow.lock_planning()
        old = uow.schedule_scopes.get(owner, scope_id)
        if old is None:
            raise LookupError("scope not found")
        if old.version != expected_version:
            raise RuleConflict("scope version changed")
        if state not in ("ACTIVE", "INACTIVE"):
            raise ValueError("invalid scope state")
        if any(s.id != old.id and s.name.casefold() == name.casefold()
               for s in uow.schedule_scopes.list_owner(owner)):
            raise RuleConflict("a scope with this name already exists")
        if state == "INACTIVE":
            if any(v.scope_id == scope_id for v in uow.work_types.list_owner(owner)):
                raise RuleConflict("scope has work types; it cannot be disabled")
            if any(r.scope_id == scope_id for rule in
                   uow.recurring_availability.list_owner(owner) for r in rule.revisions):
                raise RuleConflict("scope contains recurring availability")
        new = replace(old, name=name, state=state, version=old.version + 1)
        uow.schedule_scopes.save(new, expected_version)
        uow.schedule_scopes.audit(owner, "SCOPE_UPDATED",
                                  {"before": asdict(old), "after": asdict(new)}, None)
        uow.commit()
        return new
