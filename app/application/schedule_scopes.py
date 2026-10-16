"""TP-024A: owner-scoped parents and explicitly confirmed, dated affiliation.

No inference from WorkType names and no implicit rewrite of legacy rules,
exceptions, manual blocks or confirmed local reservations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.effective_availability import _weeks
from app.application.uow import UnitOfWork
from app.domain.effective_availability import project_effective
from app.domain.recurring_availability import RuleConflict, RuleKind
from app.domain.schedule_scopes import (
    ScheduleScope, ScopeAffiliation, compatibility_scope_id, effective_scope,
)


@dataclass(frozen=True)
class AffiliationDraft:
    work_type_id: UUID
    scope_id: UUID
    effective_from: date
    timezone_name: str
    expected_affiliation_version: int
    expected_scope_version: int
    remap_rule_ids: tuple[UUID, ...] = ()


def _digest(value: object) -> str:
    return sha256(json.dumps(value, default=str, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def _validate_name(name: str) -> str:
    if not name.strip() or len(name) > 200:
        raise ValueError("scope name must be 1-200 characters")
    return name.strip()


def list_scopes(uow: UnitOfWork, owner: str) -> dict:
    with uow:
        return {
            "scopes": [asdict(scope) for scope in uow.schedule_scopes.list_owner(owner)],
            "compatibility_scope_id": compatibility_scope_id(owner),
            "affiliations": [asdict(value) for value in
                             uow.schedule_scopes.affiliations(owner)],
            "affiliation_versions": uow.schedule_scopes.versions(owner),
            "legacy_unassigned_work_type_ids": sorted(
                str(v.id) for v in uow.work_types.list_all()
                if not any(a.work_type_id == v.id
                           for a in uow.schedule_scopes.affiliations(owner))),
        }


def create_scope(uow: UnitOfWork, owner: str, name: str) -> ScheduleScope:
    name = _validate_name(name)
    with uow:
        uow.lock_planning()
        if any(s.name.casefold() == name.casefold()
               for s in uow.schedule_scopes.list_owner(owner)):
            raise RuleConflict("a scope with this name already exists")
        uow.schedule_scopes.ensure_compatibility(owner)
        new = ScheduleScope(uuid4(), owner, name)
        uow.schedule_scopes.add(new)
        uow.schedule_scopes.audit(owner, "SCOPE_CREATED", asdict(new), None)
        uow.commit()
        return new


def update_scope(uow: UnitOfWork, owner: str, scope_id: UUID,
                 expected_version: int, name: str, state: str) -> ScheduleScope:
    name = _validate_name(name)
    with uow:
        uow.lock_planning()
        old = uow.schedule_scopes.get(owner, scope_id)
        if old is None:
            raise LookupError("scope not found")
        if old.is_compatibility:
            raise ValueError("compatibility scope cannot be renamed or disabled")
        if old.version != expected_version:
            raise RuleConflict("scope version changed")
        if state not in ("ACTIVE", "INACTIVE"):
            raise ValueError("invalid scope state")
        if any(s.id != old.id and s.name.casefold() == name.casefold()
               for s in uow.schedule_scopes.list_owner(owner)):
            raise RuleConflict("a scope with this name already exists")
        if state == "INACTIVE":
            # Do not orphan time windows or effective/future affiliations.
            if any(a.scope_id == scope_id for a in
                   uow.schedule_scopes.affiliations(owner)):
                raise RuleConflict("scope has affiliated leaves; reclassify explicitly")
            if any(rev.scope_id == scope_id for rule in
                   uow.recurring_availability.list_owner(owner)
                   for rev in rule.revisions):
                raise RuleConflict("scope contains schedule rules; revise them first")
        new = replace(old, name=name, state=state, version=old.version + 1)
        uow.schedule_scopes.save(new, expected_version)
        uow.schedule_scopes.audit(owner, "SCOPE_UPDATED",
                                  {"before": asdict(old), "after": asdict(new)}, None)
        uow.commit()
        return new


def _plan(uow: UnitOfWork, owner: str, draft: AffiliationDraft):
    if draft.expected_affiliation_version < 0 or draft.expected_scope_version < 1:
        raise ValueError("expected versions are required")
    try:
        zone = ZoneInfo(draft.timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    if draft.effective_from <= datetime.now(zone).date():
        raise ValueError("affiliation must take effect tomorrow or later (IANA civil date)")
    scope = uow.schedule_scopes.get(owner, draft.scope_id)
    if scope is None or scope.state != "ACTIVE":
        raise LookupError("active scope not found for owner")
    if scope.version != draft.expected_scope_version:
        raise RuleConflict("scope version changed; preview again")
    work_type = uow.work_types.get(draft.work_type_id)
    if work_type is None:
        raise LookupError("WorkType not found")
    aff = tuple(uow.schedule_scopes.affiliations(owner))
    versions = uow.schedule_scopes.versions(owner)
    version = versions.get(str(draft.work_type_id), 0)
    if draft.expected_affiliation_version != version:
        raise RuleConflict("affiliation version changed; preview again")
    if len(set(draft.remap_rule_ids)) != len(draft.remap_rule_ids):
        raise ValueError("duplicate remap rule ID")
    rules = tuple(uow.recurring_availability.list_owner(owner))
    exceptions = tuple(uow.availability_exceptions.list_owner(owner))
    bookings = tuple(uow.time_blocks.list_all_confirmed())
    last_day = draft.effective_from + timedelta(days=93)
    manual = tuple(b for week in _weeks(draft.effective_from, last_day)
                   for b in uow.availability.list_week(week))
    # Never mutate a source's earlier civil history. A simple entire-series
    # cutover is safe only if no later dated configuration would be overridden.
    remapped = {}
    unresolved = []
    requested = set(draft.remap_rule_ids)
    for rule in rules:
        if rule.id not in requested:
            continue
        later = [r for r in rule.revisions if r.effective_from > draft.effective_from]
        present = [r for r in rule.revisions if r.effective_from <= draft.effective_from]
        if (later or not present or
                any(r.supersedes_future for r in present)):
            unresolved.append({"rule_id": str(rule.id),
                               "reason": "future/terminal revisions require a weekly batch decision"})
            continue
        active = max(present, key=lambda r: (r.effective_from, r.number))
        if active.kind is RuleKind.CATEGORIZED:
            if active.work_type_id != draft.work_type_id:
                raise ValueError("remap must target this WorkType's categorized series")
        elif active.kind is RuleKind.GENERAL:
            # Moving the containing GENERAL envelope is explicit, never an
            # implied consequence of relocating one WorkType.
            if active.scope_id is not None:
                raise ValueError("general envelope must be a legacy source to migrate")
        else:
            raise ValueError("unsupported source series kind")
        remapped[rule.id] = replace(active, number=rule.version+1,
                                    effective_from=draft.effective_from,
                                    valid_until=None, scope_id=draft.scope_id)
    missing = requested - set(remapped) - {UUID(v["rule_id"]) for v in unresolved}
    if missing:
        raise LookupError("a requested remap series was not found for this owner")
    # A leaf's persisted future schedule must not silently remain in the
    # former scope beyond 93 days. The migration is explicit or refused.
    for rule in rules:
        if rule.id in requested:
            continue
        checkpoints = [draft.effective_from] + sorted({
            rev.effective_from for rev in rule.revisions
            if rev.effective_from > draft.effective_from
        })
        for checkpoint in checkpoints:
            applicable = [rev for rev in rule.revisions
                          if rev.effective_from <= checkpoint]
            if not applicable or any(rev.supersedes_future for rev in applicable):
                continue
            active = max(applicable, key=lambda rev: (rev.effective_from, rev.number))
            if (active.enabled
                    and (active.valid_until is None or checkpoint < active.valid_until)
                    and active.kind is RuleKind.CATEGORIZED
                    and active.work_type_id == draft.work_type_id
                    and active.scope_id != draft.scope_id):
                unresolved.append({
                    "rule_id": str(rule.id),
                    "reason": "future categorized occurrence must be explicitly migrated",
                })
                break
    next_rules = tuple(replace(rule, version=rule.version+1,
                               revisions=rule.revisions+(remapped[rule.id],))
                       if rule.id in remapped else rule for rule in rules)
    next_aff = aff + (ScopeAffiliation(
        draft.work_type_id, draft.scope_id, owner,
        draft.effective_from, version+1),)
    # All revisions and exceptions are preserved, and need explicit remap.
    # Inventory beyond the numeric 93-day horizon is not truncated.
    inventory = []
    for rule in rules:
        for rev in rule.revisions:
            if (rev.work_type_id == draft.work_type_id
                    and not rev.supersedes_future
                    and (rev.valid_until is None or rev.valid_until > draft.effective_from)):
                inventory.append({"rule_id": str(rule.id), "revision": rev.number,
                                  "scope_id": str(rev.scope_id or compatibility_scope_id(owner)),
                                  "explicitly_remapped": rule.id in remapped})
    pending_exceptions = [
        {"exception_id": str(e.id), "action": e.action.value, "rule_id":
         str(e.rule_id) if e.rule_id else None, "scope_id":
         str(e.scope_id) if e.scope_id else None}
        for e in exceptions if e.enabled and (
            e.work_type_id == draft.work_type_id or
            e.rule_id in remapped or
            any(r.id == e.rule_id and any(v.work_type_id == draft.work_type_id
                                          for v in r.revisions) for r in rules))]
    affected_manual = [
        {"block_id": str(v.id), "starts_at": v.starts_at.isoformat()}
        for v in manual if v.work_type_id == draft.work_type_id
    ]
    future_bookings = [{
        "booking_id": str(b.id), "work_type_id":
        str(b.work_type_id) if b.work_type_id else None,
        "scope_id": str(b.scope_id) if b.scope_id else None,
        "starts_at": b.starts_at.isoformat(), "status": b.status,
    } for b in bookings
        if b.starts_at.astimezone(zone).date() >= draft.effective_from
        and (b.work_type_id == draft.work_type_id
             or b.transferred_from == draft.work_type_id)]
    old = project_effective(rules, exceptions, manual, bookings,
                            draft.effective_from, last_day, draft.timezone_name,
                            compatibility_id=compatibility_scope_id(owner),
                            affiliations=aff)
    new = project_effective(next_rules, exceptions, manual, bookings,
                            draft.effective_from, last_day, draft.timezone_name,
                            compatibility_id=compatibility_scope_id(owner),
                            affiliations=next_aff)
    structural = {"INCOMPATIBLE_SCOPES", "AFFILIATION_SCOPE_MISMATCH",
                  "OUTSIDE_GENERAL_ENVELOPE", "INCOMPATIBLE_WORK_TYPES",
                  "INCOMPATIBLE_MODES"}
    earlier = {}
    for issue in old.issues:
        if issue.code in structural:
            key = (issue.code, tuple(sorted(issue.scope_ids)))
            earlier.setdefault(key, []).append((issue.starts_at, issue.ends_at))
    conflict_rows = []
    for issue in new.issues:
        if issue.code not in structural:
            continue
        key = (issue.code, tuple(sorted(issue.scope_ids)))
        cuts = {issue.starts_at, issue.ends_at}
        for a, b in earlier.get(key, []):
            if a < issue.ends_at and b > issue.starts_at:
                cuts.update((max(a, issue.starts_at), min(b, issue.ends_at)))
        for a, b in zip(sorted(cuts), sorted(cuts)[1:]):
            preexisting = any(x <= a and y >= b for x, y in earlier.get(key, []))
            conflict_rows.append({
                "code": issue.code, "status": "PREEXISTING" if preexisting else "NEW",
                "starts_at": a.isoformat(), "ends_at": b.isoformat(),
                "scope_ids": [str(s) for s in issue.scope_ids],
                "sources": list(issue.sources),
            })
    def by_scope(projection):
        totals = {}
        for block in projection.blocks:
            key = str(block.scope_id) if block.scope_id else "UNSCOPED"
            totals[key] = totals.get(key, 0) + block.minutes
        return totals
    sources = {
        "draft": asdict(draft), "scope": asdict(scope),
        "scopes": [asdict(s) for s in uow.schedule_scopes.list_owner(owner)],
        "versions": versions, "affiliations": [asdict(a) for a in aff],
        "rules": [asdict(rule) for rule in rules],
        "exceptions": [asdict(e) for e in exceptions],
        "manual": [asdict(b) for b in manual],
        "bookings": [asdict(b) for b in bookings],
        "work_types": [asdict(w) for w in uow.work_types.list_all()],
    }
    preview = {
        "algorithm": "TP-024A/v1+TP-023D/v2",
        "fingerprint": _digest(sources),
        "projection_days": 93, "calendar_verified": False,
        "effective_from": draft.effective_from.isoformat(),
        "work_type_id": str(draft.work_type_id),
        "from_scope_id": str(effective_scope(
            draft.work_type_id, draft.effective_from, aff,
            compatibility_scope_id(owner))),
        "to_scope_id": str(draft.scope_id),
        "before_minutes_93d": by_scope(old),
        "after_minutes_93d": by_scope(new),
        "global_before_minutes_93d": old.declared_minutes,
        "global_after_minutes_93d": new.declared_minutes,
        "conflicts": conflict_rows, "civil_time_issues": [
            {"rule_id": str(i.rule_id), "date": str(i.original_local_date),
             "reason": i.reason} for i in new.expansion_issues],
        "rules_inventory": inventory, "exceptions_inventory": pending_exceptions,
        "explicit_general_envelope_remaps": [str(rule.id) for rule in rules
            if rule.id in remapped and remapped[rule.id].kind is RuleKind.GENERAL],
        "manual_blocks_inventory": affected_manual,
        "all_future_bookings": future_bookings,
        "unresolved_rule_migrations": unresolved,
        "explicitly_remapped_rule_ids": [str(x) for x in sorted(remapped, key=str)],
        "has_changes": bool(remapped) or effective_scope(
            draft.work_type_id, draft.effective_from, aff,
            compatibility_scope_id(owner)) != draft.scope_id,
    }
    return preview, remapped


def preview_affiliation(uow: UnitOfWork, owner: str, draft: AffiliationDraft) -> dict:
    with uow:
        return _plan(uow, owner, draft)[0]


def confirm_affiliation(uow: UnitOfWork, owner: str, draft: AffiliationDraft, *,
                        fingerprint: str, command_id: UUID,
                        confirmed: bool, acknowledge_bookings: bool) -> dict:
    if not confirmed:
        raise ValueError("explicit confirmation is required")
    payload_hash = _digest({"draft": asdict(draft),
                            "acknowledge_bookings": acknowledge_bookings})
    with uow:
        uow.lock_planning()
        receipt = uow.schedule_scopes.command(owner, command_id)
        if receipt is not None:
            if receipt.payload_hash != payload_hash:
                raise RuleConflict("command_id reused with different draft")
            return receipt.result
        preview, remapped = _plan(uow, owner, draft)
        if preview["fingerprint"] != fingerprint:
            raise RuleConflict("affiliation preview is stale; preview again")
        if preview["unresolved_rule_migrations"]:
            raise ValueError("resolve ambiguous future rule revisions explicitly")
        if preview["exceptions_inventory"] or preview["manual_blocks_inventory"]:
            # Never silently re-scope standalone exceptions or mutable manual
            # blocks without a separately specified remediation.
            raise ValueError("resolve affected exceptions/manual blocks explicitly")
        if any(c["status"] == "NEW" for c in preview["conflicts"]):
            raise ValueError("scope change would create structural conflicts")
        if preview["civil_time_issues"]:
            raise ValueError("invalid or ambiguous IANA civil time")
        if preview["all_future_bookings"] and not acknowledge_bookings:
            raise ValueError("acknowledge preserved future bookings and provenance")
        if not preview["has_changes"]:
            result = {"applied": False, "command_id": str(command_id),
                      "calendar_written": False, "fingerprint": fingerprint}
        else:
            if draft.scope_id == compatibility_scope_id(owner):
                uow.schedule_scopes.ensure_compatibility(owner)
            changed = uow.schedule_scopes.attach(
                owner, draft.work_type_id, draft.scope_id,
                draft.effective_from, draft.expected_affiliation_version)
            for rule_id, revision in remapped.items():
                source = uow.recurring_availability.get(rule_id, owner)
                if source is None:
                    raise RuleConflict("source rule was deleted during confirmation")
                uow.recurring_availability.append_revision(
                    revision, expected_version=source.version)
            result = {
                "applied": True, "command_id": str(command_id),
                "scope_id": str(changed.scope_id),
                "work_type_id": str(changed.work_type_id),
                "affiliation_version": changed.version,
                "preserved_booking_ids": [b["booking_id"]
                                         for b in preview["all_future_bookings"]],
                "calendar_written": False, "fingerprint": fingerprint,
            }
            uow.schedule_scopes.audit(
                owner, "AFFILIATION_CONFIRMED",
                {"draft": asdict(draft), "preview": preview}, command_id)
        uow.schedule_scopes.receipt(owner, command_id, payload_hash, result)
        uow.commit()
        return result
