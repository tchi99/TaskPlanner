"""TP-023A: one authoritative future weekly edit, previewed and committed atomically.

Changes are scoped to explicit weekday/section keys. Existing multi-day
series are closed at the cutover and their *unselected* future timeline is
copied to traceable children; no previous revision is rewritten.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.application.effective_availability import _weeks
from app.application.history import HistoryEvent, HistorySource
from app.application.uow import UnitOfWork
from app.domain.effective_availability import project_effective
from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleConflict, RuleKind,
    RuleRevision, _wall_clock,
)
from app.domain.availability_exceptions import AvailabilityException
from app.domain.schedule_scopes import compatibility_scope_id, effective_scope


ALGORITHM = "TP-024A/v1+TP-023D/v2"
_INVALID = {"OUTSIDE_GENERAL_ENVELOPE", "INCOMPATIBLE_WORK_TYPES", "INCOMPATIBLE_MODES",
            "INCOMPATIBLE_SCOPES", "AFFILIATION_SCOPE_MISMATCH"}


@dataclass(frozen=True)
class Slot:
    starts_at_local: str
    ends_at_local: str
    mode: AvailabilityMode | None = None
    start_fold: int | None = None
    end_fold: int | None = None


@dataclass(frozen=True)
class Section:
    weekday: int
    kind: RuleKind
    work_type_id: UUID | None
    slots: tuple[Slot, ...]
    scope_id: UUID | None = None


@dataclass(frozen=True)
class ExceptionDecision:
    exception_id: UUID
    expected_version: int
    action: str  # REMAP or DISABLE, never an implicit ADD
    target_rule_id: UUID | None = None


@dataclass(frozen=True)
class WeeklyDraft:
    effective_from: date
    timezone_name: str
    sections: tuple[Section, ...]
    expected_versions: dict[str, int]
    exception_decisions: tuple[ExceptionDecision, ...] = ()


def _encode(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _digest(value) -> str:
    return sha256(_encode(value).encode()).hexdigest()


def _key(weekday: int, kind: RuleKind, work_type_id: UUID | None, zone: str,
         scope_id: UUID | None = None):
    return weekday, kind, work_type_id, zone, scope_id


def _key_str(key) -> str:
    legacy = f"{key[0]}:{key[1].value}:{key[2] or 'NULL'}:{key[3]}"
    return legacy if key[4] is None else f"{legacy}:SCOPE:{key[4]}"


def _active(rule: RecurringAvailabilityRule, day: date) -> RuleRevision | None:
    applicable = [r for r in rule.revisions if r.effective_from <= day]
    if any(r.supersedes_future for r in applicable):
        return None
    if not applicable:
        return None
    rev = max(applicable, key=lambda r: (r.effective_from, r.number))
    if not rev.enabled or (rev.valid_until is not None and day >= rev.valid_until):
        return None
    return rev


def _dates(rules, effect: date) -> list[date]:
    return sorted({effect} |
                  {r.effective_from for rule in rules for r in rule.revisions
                   if r.effective_from >= effect} |
                  {r.valid_until for rule in rules for r in rule.revisions
                   if r.valid_until is not None and r.valid_until >= effect})


def _slots_for(rules, when: date, key) -> tuple[Slot, ...]:
    weekday, kind, work_type, zone, scope = key
    answer = []
    for rule in rules:
        rev = _active(rule, when)
        if (rev is not None and weekday in rev.days_of_week and
                rev.kind is kind and rev.work_type_id == work_type and
                rev.timezone_name == zone and rev.scope_id == scope):
            answer.append(Slot(rev.starts_at_local, rev.ends_at_local, rev.mode,
                               rev.start_fold, rev.end_fold))
    return tuple(sorted(answer, key=lambda s: (s.starts_at_local, s.ends_at_local,
                                             str(s.mode), str(s.start_fold), str(s.end_fold))))


def _validate(draft: WeeklyDraft, uow: UnitOfWork, owner: str) -> dict:
    if not draft.sections or len(draft.sections) > 100:
        raise ValueError("select 1 to 100 weekday/section cells")
    if not draft.timezone_name or len(draft.timezone_name) > 100:
        raise ValueError("invalid timezone")
    try:
        today = datetime.now(ZoneInfo(draft.timezone_name)).date()
    except (KeyError, ValueError) as exc:
        raise ValueError("unknown IANA timezone") from exc
    if draft.effective_from <= today:
        raise ValueError("weekly changes must take effect tomorrow or later (local civil date)")
    keys = {}
    for section in draft.sections:
        day = section.weekday
        if type(day) is not int or not 0 <= day <= 6:
            raise ValueError("weekday must be 0..6")
        if section.kind is not RuleKind.GENERAL:
            raise ValueError("only parent GENERAL envelopes can be edited here")
        if section.scope_id is None:
            raise ValueError("a real owned parent is required for each envelope")
        if section.work_type_id is not None:
            raise ValueError("GENERAL section must not declare a work type")
        if section.scope_id is not None:
            scope = uow.schedule_scopes.get(owner, section.scope_id)
            if scope is None or scope.state != "ACTIVE":
                raise ValueError("section scope is not active or owned by this user")
        key = _key(day, section.kind, section.work_type_id,
                   draft.timezone_name, section.scope_id)
        if key in keys:
            raise ValueError("duplicate weekday/section cell")
        prev_end = -1
        ordered = sorted(section.slots, key=lambda s: (s.starts_at_local, s.ends_at_local))
        if len(ordered) > 30:
            raise ValueError("too many intervals in one weekday/section")
        for slot in ordered:
            begin = _wall_clock(slot.starts_at_local)
            finish = _wall_clock(slot.ends_at_local, end=True)
            if begin >= finish or begin < prev_end:
                raise ValueError("intervals in one cell must be positive and disjoint")
            if slot.mode is not None:
                raise ValueError("GENERAL slots cannot use old PROTECTED/PREFERRED modes")
            if slot.start_fold not in (None, 0, 1) or slot.end_fold not in (None, 0, 1):
                raise ValueError("DST fold must be 0 or 1")
            prev_end = finish
        keys[key] = tuple(ordered)
    decisions = {d.exception_id: d for d in draft.exception_decisions}
    if len(decisions) != len(draft.exception_decisions):
        raise ValueError("duplicate exception decisions")
    if any(d.expected_version < 1 or d.action not in ("REMAP", "DISABLE") or
           (d.action == "REMAP" and d.target_rule_id is None) or
           (d.action == "DISABLE" and d.target_rule_id is not None)
           for d in decisions.values()):
        raise ValueError("invalid exception decision")
    return keys


def _make_rule(rule_id: UUID, owner: str, revisions: list[RuleRevision]) -> RecurringAvailabilityRule:
    return RecurringAvailabilityRule(rule_id, owner, len(revisions), tuple(revisions))


def _rev(rule_id: UUID, number: int, when: date, day: int,
         kind: RuleKind, work_type_id: UUID | None, zone: str, slot: Slot,
         enabled: bool = True, scope_id: UUID | None = None) -> RuleRevision:
    return RuleRevision(
        rule_id, number, when, None, zone, (day,),
        slot.starts_at_local, slot.ends_at_local, kind, work_type_id,
        slot.mode, enabled, slot.start_fold, slot.end_fold,
        scope_id=scope_id,
    )


def _future_keys(rule: RecurringAvailabilityRule, effect: date):
    """Every weekday/section that remains active at or after cutover."""
    result = set()
    for when in _dates((rule,), effect):
        rev = _active(rule, when)
        if rev is not None:
            result.update(_key(day, rev.kind, rev.work_type_id, rev.timezone_name, rev.scope_id)
                          for day in rev.days_of_week)
    return result


def _child(rule, key, effect, identity) -> RecurringAvailabilityRule | None:
    day, kind, work_type, zone, scope = key
    revisions = []
    last = None
    for when in _dates((rule,), effect):
        active = _active(rule, when)
        matches = (active is not None and day in active.days_of_week and
                   active.kind is kind and active.work_type_id == work_type and
                   active.timezone_name == zone and active.scope_id == scope)
        slot = (Slot(active.starts_at_local, active.ends_at_local, active.mode,
                     active.start_fold, active.end_fold) if matches else None)
        if slot == last:
            continue
        if slot is None:
            if revisions:
                old = revisions[-1]
                revisions.append(replace(old, number=len(revisions)+1,
                                         effective_from=when, enabled=False,
                                         valid_until=None))
        else:
            revisions.append(_rev(identity, len(revisions)+1, when, day,
                                  kind, work_type, zone, slot, scope_id=scope))
        last = slot
    return _make_rule(identity, rule.owner_id, revisions) if revisions else None


def _event(entity_id: UUID, entity_type: str, event: str, correlation: UUID,
           payload: dict) -> HistoryEvent:
    now = datetime.now(timezone.utc)
    return HistoryEvent(
        id=uuid4(), occurred_at=now, recorded_at=now, entity_type=entity_type,
        entity_id=entity_id, task_id=None, event_type=event, schema_version=1,
        source=HistorySource.USER, reason_code=None,
        correlation_id=correlation, causation_id=None, payload=payload,
    )



def _invalid_details(before, after, original_rules, future_rules,
                     original_exceptions, future_exceptions, manual, zone: str):
    """Classify *minutes* of structural errors, not projector partition IDs.

    Changing a GENERAL interval can shorten/split an existing invalid span;
    it cannot create a new error merely because its (start, end) changed.
    Category identities remain stable even when a revised rule gets a new UUID.
    """
    local_zone = ZoneInfo(zone)

    def context(issue, rules, exceptions):
        rule_by_id = {str(rule.id): rule for rule in rules}
        exception_by_id = {str(exc.id): exc for exc in exceptions}
        manual_by_id = {str(block.id): block for block in manual}
        types, rule_ids, source_zones, source_dates = set(), set(), set(), set()
        for source in issue.sources:
            parts = source.split(":")
            if parts[0] == "RULE" and len(parts) >= 4:
                rule = rule_by_id.get(parts[1])
                if rule is None:
                    continue
                rule_ids.add(parts[1])
                source_dates.add(parts[2])
                revision = next((rev for rev in rule.revisions
                                 if "v" + str(rev.number) == parts[3]), None)
                if revision is not None:
                    source_zones.add(revision.timezone_name)
                    if revision.kind is RuleKind.CATEGORIZED and revision.work_type_id:
                        types.add(str(revision.work_type_id))
            elif parts[0] == "EXCEPTION" and len(parts) >= 2:
                exc = exception_by_id.get(parts[1])
                if exc is not None:
                    source_zones.add(exc.timezone_name)
                    if exc.original_local_date is not None:
                        source_dates.add(exc.original_local_date.isoformat())
                    if parts[-1] != "removed" and exc.kind is RuleKind.CATEGORIZED and exc.work_type_id:
                        types.add(str(exc.work_type_id))
                    if exc.rule_id:
                        rule_ids.add(str(exc.rule_id))
            elif parts[0] == "MANUAL" and len(parts) >= 2:
                block = manual_by_id.get(parts[1])
                if block is not None and block.work_type_id:
                    types.add(str(block.work_type_id))
        return (tuple(sorted(types)), sorted(rule_ids), sorted(source_zones),
                sorted(source_dates))

    earlier = {}
    for issue in before.issues:
        if issue.code not in _INVALID:
            continue
        types, _, _, _ = context(issue, original_rules, original_exceptions)
        earlier.setdefault((issue.code, types, tuple(sorted(map(str, issue.scope_ids)))), []).append(
            (issue.starts_at, issue.ends_at))
    results = []
    new_codes = set()
    total = 0
    for issue in after.issues:
        if issue.code not in _INVALID:
            continue
        types, rule_ids, source_zones, source_dates = context(
            issue, future_rules, future_exceptions)
        prior = earlier.get((issue.code, types, tuple(sorted(map(str, issue.scope_ids)))), [])
        cuts = {issue.starts_at, issue.ends_at}
        for left, right in prior:
            if left < issue.ends_at and right > issue.starts_at:
                cuts.add(max(left, issue.starts_at))
                cuts.add(min(right, issue.ends_at))
        points = sorted(cuts)
        for start, end in zip(points, points[1:]):
            preexisting = any(left <= start and right >= end for left, right in prior)
            status = "PREEXISTING" if preexisting else "NEW"
            if not preexisting:
                new_codes.add(issue.code)
            total += 1
            results.append({
                "code": issue.code, "status": status,
                "date": start.astimezone(local_zone).date().isoformat(),
                "timezone_name": zone, "weekday": start.astimezone(local_zone).weekday(),
                "starts_at": start.astimezone(local_zone).isoformat(),
                "ends_at": end.astimezone(local_zone).isoformat(),
                "work_type_id": types[0] if len(types) == 1 else None,
                "work_type_ids": list(types), "rule_ids": rule_ids,
                "scope_ids": [str(v) for v in issue.scope_ids],
                "sources": list(issue.sources), "source_timezones": source_zones,
                "source_local_dates": source_dates,
                "cause": ("REMOVED_BY_EXCEPTION" if any(
                    s.endswith(":removed") for s in issue.sources)
                    else "NO_COVERING_GENERAL" if issue.code == "OUTSIDE_GENERAL_ENVELOPE"
                    else "OVERLAPPING_DECLARATIONS"),
                "remediation": (
                    "Élargir ou réparer l'enveloppe générale, ajuster la catégorie, "
                    "ou modifier les deux sections dans le même brouillon."
                    if issue.code == "OUTSIDE_GENERAL_ENVELOPE"
                    else "Corriger les plages ou modes qui se chevauchent dans un même brouillon."),
            })
    # Prioritize newly introduced violations even if historic data contains
    # hundreds of unrelated old fragments across the 93-day window.
    results.sort(key=lambda row: (row["status"] != "NEW", row["starts_at"],
                                  row["code"], row["work_type_ids"]))
    return sorted(new_codes), results[:500], total > 500


def _plan(uow: UnitOfWork, owner: str, draft: WeeklyDraft):
    requested = _validate(draft, uow, owner)
    rules = tuple(uow.recurring_availability.list_owner(owner))
    exceptions = tuple(uow.availability_exceptions.list_owner(owner))
    bookings = tuple(uow.time_blocks.list_all_confirmed())
    days = _dates(rules, draft.effective_from)
    for key, version in draft.expected_versions.items():
        matching = next((v for v in rules if str(v.id) == key), None)
        if matching is None or matching.version != version:
            raise RuleConflict("weekly source versions changed; reload before preview")
    modified = {key: slots for key, slots in requested.items()
                if any(_slots_for(rules, when, key) != slots for when in days)}
    content_hash = _digest(asdict(draft))
    lineage = _digest([(str(r.id), r.version, asdict(r.revisions[-1])) for r in rules])
    def identity(suffix):
        return uuid5(NAMESPACE_URL, f"{owner}:{content_hash}:{lineage}:{suffix}")
    affected = {}
    children = {}
    additions = {}
    for rule in rules:
        source_keys = _future_keys(rule, draft.effective_from)
        touched = source_keys & set(modified)
        if not touched:
            continue
        terminal = replace(rule.revisions[-1], number=rule.version+1,
                           effective_from=draft.effective_from, valid_until=None,
                           enabled=False, supersedes_future=True)
        affected[rule.id] = (rule, terminal)
        for key in sorted(source_keys - set(modified), key=_key_str):
            ident = identity(f"child:{rule.id}:{_key_str(key)}")
            child = _child(rule, key, draft.effective_from, ident)
            if child is not None:
                children[ident] = (child, rule.id)
    for key, slots in sorted(modified.items(), key=lambda x: _key_str(x[0])):
        for index, slot in enumerate(slots):
            rule_id = identity(f"slot:{_key_str(key)}:{index}")
            rev = _rev(rule_id, 1, draft.effective_from, key[0], key[1],
                       key[2], key[3], slot, scope_id=key[4])
            additions[rule_id] = (_make_rule(rule_id, owner, [rev]), None)
    before_ids = set(affected)
    # Only rule snapshots (not the precomputed tuple above) reach the projector.
    revised = tuple(_make_rule(r.id, r.owner_id,
                              list(r.revisions)+[affected[r.id][1]])
                    if r.id in before_ids else r for r in rules)
    future_rules = revised + tuple(r for r, _ in (*children.values(), *additions.values()))
    assignments = {}
    unresolved = []
    decisions = {item.exception_id: item for item in draft.exception_decisions}
    changed_exceptions = {}
    for exc in exceptions:
        if not exc.enabled or exc.rule_id not in before_ids or (
                exc.original_local_date is None or exc.original_local_date < draft.effective_from):
            continue
        source = affected[exc.rule_id][0]
        date_ = exc.original_local_date
        old = _active(source, date_)
        choices = []
        for target, _ in (*children.values(), *additions.values()):
            revision = _active(target, date_)
            if revision is None or date_.weekday() not in revision.days_of_week:
                continue
            if (old is not None and revision.kind is old.kind
                    and revision.work_type_id == old.work_type_id
                    and revision.scope_id == old.scope_id):
                choices.append(target)
        exact = [r for r in choices if old is not None and
                 (v := _active(r, date_)) is not None and
                 (v.starts_at_local, v.ends_at_local, v.mode) ==
                 (old.starts_at_local, old.ends_at_local, old.mode)]
        action = decisions.get(exc.id)
        if action is not None and action.expected_version != exc.version:
            raise RuleConflict("exception version changed; preview again")
        if action is None and len(exact) == 1:
            assignments[exc.id] = ("REMAP", exact[0].id)
        elif action is not None and action.action == "DISABLE":
            assignments[exc.id] = ("DISABLE", None)
        elif action is not None and action.action == "REMAP" and any(
                r.id == action.target_rule_id for r in choices):
            assignments[exc.id] = ("REMAP", action.target_rule_id)
        else:
            unresolved.append({"exception_id": str(exc.id), "version": exc.version,
                               "candidate_rule_ids": [str(r.id) for r in choices],
                               "reason": "explicit REMAP or DISABLE required"})
    unused = set(decisions) - set(assignments) - {
        UUID(e["exception_id"]) for e in unresolved}
    if unused:
        raise ValueError("exception decision does not belong to this edit")
    for exc in exceptions:
        if exc.id not in assignments:
            continue
        action, target = assignments[exc.id]
        changed_exceptions[exc.id] = replace(
            exc, rule_id=target if action == "REMAP" else exc.rule_id,
            enabled=exc.enabled if action == "REMAP" else False,
            version=exc.version+1,
        )
    proposed_exceptions = tuple(changed_exceptions.get(e.id, e) for e in exceptions)
    # Owner/rule/origin is unique in SQL: fail during preview, not halfway
    # through confirmation, and never silently discard an exception.
    targeted = {}
    for exc in proposed_exceptions:
        if exc.rule_id is None or exc.original_local_date is None:
            continue
        key = (exc.owner_id, exc.rule_id, exc.original_local_date)
        previous = targeted.setdefault(key, exc.id)
        if previous != exc.id:
            raise RuleConflict("multiple exceptions would target the same revised occurrence")
    # A preview is explicitly bounded to 93 civil days, not an assertion that
    # the remainder of an infinite recurrence has no future Google conflicts.
    end = draft.effective_from + timedelta(days=93)
    manual = tuple(b for week in _weeks(draft.effective_from, end)
                   for b in uow.availability.list_week(week))
    bounded_bookings = tuple(b for b in bookings if
                             b.starts_at.astimezone(ZoneInfo(draft.timezone_name)).date() < end and
                             b.ends_at.astimezone(ZoneInfo(draft.timezone_name)).date() >= draft.effective_from)
    # Existing shared bookings must be compared against both the physical
    # envelope and their dated permissions before and after a legacy edit.
    from app.domain.eligibility_projection import (
        project_eligibility, reconcile_booking_issues,
    )
    shared_series = tuple(uow.eligibility.list_owner(owner))
    shared_exceptions = tuple(uow.eligibility.list_exceptions(owner))
    compatibility = compatibility_scope_id(owner)
    affiliations = uow.schedule_scopes.affiliations(owner)

    def with_shared(physical, booked, start_date, end_date):
        eligibility = project_eligibility(
            physical, shared_series, shared_exceptions,
            start_date, end_date, draft.timezone_name,
            compatibility_id=compatibility, affiliations=affiliations,
        )
        return reconcile_booking_issues(physical, eligibility, booked,
                                        compatibility)

    before = project_effective(rules, exceptions, manual, bounded_bookings,
                               draft.effective_from, end, draft.timezone_name,
                               compatibility_id=compatibility_scope_id(owner),
                               affiliations=uow.schedule_scopes.affiliations(owner))
    after = project_effective(future_rules, proposed_exceptions, manual, bounded_bookings,
                              draft.effective_from, end, draft.timezone_name,
                              compatibility_id=compatibility_scope_id(owner),
                              affiliations=uow.schedule_scopes.affiliations(owner))
    before, before_permissions = with_shared(before, bounded_bookings, draft.effective_from, end)
    after, after_permissions = with_shared(after, bounded_bookings, draft.effective_from, end)
    invalid, diagnostics, diagnostics_truncated = _invalid_details(
        before, after, rules, future_rules, exceptions, proposed_exceptions,
        manual, draft.timezone_name)
    # A parent GENERAL reduction must not create a new permission outside its
    # physical envelope. Compare UTC coverage, not newly split fragment IDs.
    prior = {}
    for issue in before_permissions.issues:
        if issue.code in ("ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE",
                          "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE",
                          "ELIGIBILITY_SCOPE_MISMATCH"):
            prior.setdefault((issue.code, tuple(issue.scope_ids)), []).append(
                (issue.starts_at, issue.ends_at))
    for issue in after_permissions.issues:
        if issue.code not in ("ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE",
                              "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE",
                              "ELIGIBILITY_SCOPE_MISMATCH"):
            continue
        spans = prior.get((issue.code, tuple(issue.scope_ids)), ())
        if any(a <= issue.starts_at and b >= issue.ends_at for a, b in spans):
            continue
        invalid = sorted(set(invalid) | {issue.code})
        diagnostics.append({
            "code": issue.code, "status": "NEW",
            "date": issue.starts_at.astimezone(ZoneInfo(draft.timezone_name)).date().isoformat(),
            "timezone_name": draft.timezone_name,
            "starts_at": issue.starts_at.astimezone(ZoneInfo(draft.timezone_name)).isoformat(),
            "ends_at": issue.ends_at.astimezone(ZoneInfo(draft.timezone_name)).isoformat(),
            "scope_ids": [str(scope) for scope in issue.scope_ids],
            "sources": list(issue.sources),
            "remediation": "Adapter explicitement la permission ou conserver l'enveloppe physique.",
        })
    # Inventory ALL finite persisted bookings, even when they lie beyond the
    # 93-day numeric projection. Never mutate them in a weekly schedule edit.
    conflicts = []
    for booking in bookings:
        local = booking.starts_at.astimezone(ZoneInfo(draft.timezone_name)).date()
        if local < draft.effective_from:
            continue
        stop = local + timedelta(days=2)
        relevant_manual = tuple(b for week in _weeks(local, stop)
                                for b in uow.availability.list_week(week))
        old_p = project_effective(rules, exceptions, relevant_manual, (booking,),
                                  local, stop, draft.timezone_name,
                                  compatibility_id=compatibility_scope_id(owner),
                                  affiliations=uow.schedule_scopes.affiliations(owner))
        new_p = project_effective(future_rules, proposed_exceptions, relevant_manual,
                                  (booking,), local, stop, draft.timezone_name,
                                  compatibility_id=compatibility_scope_id(owner),
                                  affiliations=uow.schedule_scopes.affiliations(owner))
        old_p, _ = with_shared(old_p, (booking,), local, stop)
        new_p, _ = with_shared(new_p, (booking,), local, stop)
        was = any(i.booking_id == booking.id for i in old_p.issues)
        now = any(i.booking_id == booking.id for i in new_p.issues)
        if now:
            conflicts.append({"booking_id": str(booking.id),
                              "starts_at": booking.starts_at.isoformat(),
                              "new": not was})
    conflicts.sort(key=lambda row: row["booking_id"])
    snapshot = {
        "algorithm": ALGORITHM, "draft": asdict(draft),
        "rules": [asdict(v) for v in rules],
        "scopes": [asdict(v) for v in uow.schedule_scopes.list_owner(owner)],
        "scope_versions": uow.schedule_scopes.versions(owner),
        "affiliations": [asdict(v) for v in uow.schedule_scopes.affiliations(owner)],
        "exceptions": [asdict(v) for v in exceptions],
        "bookings": [asdict(v) for v in bookings],
        "manual": [asdict(v) for v in manual],
        "work_types": sorted(str(v.id) for v in uow.work_types.list_all()),
        "shared_permission_series": [asdict(v) for v in shared_series],
        "shared_permission_exceptions": [asdict(v) for v in shared_exceptions],
        "modified": sorted(_key_str(k) for k in modified),
        "conflicts": conflicts, "invalid": invalid,
        "invalid_diagnostics": diagnostics, "diagnostics_truncated": diagnostics_truncated,
        "unresolved": unresolved,
    }
    response = {
        "algorithm": ALGORITHM,
        "effective_from": draft.effective_from.isoformat(),
        "timezone_name": draft.timezone_name,
        "fingerprint": _digest(snapshot),
        "changed_sections": sorted(_key_str(k) for k in modified),
        "cell_changes": [
            {"section": _key_str(key),
             "before": [asdict(s) for s in _slots_for(rules, draft.effective_from, key)],
             "after": [asdict(s) for s in slots],
             "previous_future": [
                 {"effective_from": when.isoformat(),
                  "slots": [asdict(s) for s in _slots_for(rules, when, key)]}
                 for when in days if when > draft.effective_from
                 and _slots_for(rules, when, key) != _slots_for(rules, draft.effective_from, key)
             ]}
            for key, slots in sorted(modified.items(), key=lambda x: _key_str(x[0]))
        ],
        "series_cutovers": [{"rule_id": str(id_), "version": rule.version,
                             "future_revisions_superseded": [
                                 r.number for r in rule.revisions
                                 if r.effective_from >= draft.effective_from]}
                            for id_, (rule, _) in affected.items()],
        "derived_rule_ids": {str(id_): str(parent) for id_, (_, parent) in children.items()},
        "created_rule_ids": [str(v) for v in additions],
        "exception_remaps": [{"exception_id": str(id_), "action": action,
                              "target_rule_id": str(target) if target else None}
                             for id_, (action, target) in assignments.items()],
        "unresolved_exceptions": unresolved,
        "booking_conflicts": conflicts,
        "invalid_conflicts": invalid,
        "invalid_diagnostics": diagnostics,
        "invalid_diagnostics_truncated": diagnostics_truncated,
        "before_declared_minutes_93d": before.declared_minutes,
        "after_declared_minutes_93d": after.declared_minutes,
        "projection_days": 93,
        "civil_time_issues": [
            {"rule_id": str(v.rule_id), "revision": v.revision,
             "date": v.original_local_date.isoformat(), "reason": v.reason}
            for v in after.expansion_issues
        ],
        "calendar_verified": False,
        "has_changes": bool(modified),
    }
    return response, affected, children, additions, changed_exceptions


def read_weekly(uow: UnitOfWork, owner: str, effect: date, zone: str,
                scope_id: UUID | None = None):
    # The same future-date safety rule governs both read projection and writes.
    with uow:
        if scope_id is None:
            parents = uow.schedule_scopes.list_owner(owner)
            scope_id = parents[0].id if parents else None
        if scope_id is not None:
            _validate(WeeklyDraft(effect, zone, (Section(0, RuleKind.GENERAL, None, (), scope_id),), {}),
                      uow, owner)
        else:
            if effect <= datetime.now(ZoneInfo(zone)).date():
                raise ValueError("weekly changes must take effect tomorrow or later")
        rules = tuple(uow.recurring_availability.list_owner(owner))
        by_key = {}
        for rule in rules:
            rev = _active(rule, effect)
            if rev is None or rev.timezone_name != zone or rev.scope_id != scope_id:
                continue
            for day in rev.days_of_week:
                key = _key(day, rev.kind, rev.work_type_id, zone, rev.scope_id)
                by_key[key] = _slots_for(rules, effect, key)
        return {
            "effective_from": effect.isoformat(), "timezone_name": zone,
            "scope_id": str(scope_id) if scope_id else None,
            "source_versions": {str(r.id): r.version for r in rules
                                if any(rev.scope_id == scope_id for rev in r.revisions)},
            "sections": [{"weekday": key[0], "kind": key[1].value,
                          "work_type_id": str(key[2]) if key[2] else None,
                          "scope_id": str(key[4]) if key[4] else None,
                          "slots": [
                              {**asdict(slot), "sources": [
                                  {"rule_id": str(rule.id), "revision": rev.number}
                                  for rule in rules if (rev := _active(rule, effect)) is not None
                                  and key[0] in rev.days_of_week and rev.kind is key[1]
                                  and rev.work_type_id == key[2]
                                  and rev.timezone_name == key[3]
                                  and rev.scope_id == key[4]
                                  and (rev.starts_at_local, rev.ends_at_local,
                                       rev.mode, rev.start_fold, rev.end_fold) == (
                                      slot.starts_at_local, slot.ends_at_local,
                                      slot.mode, slot.start_fold, slot.end_fold)
                              ]}
                              for slot in slots
                          ]}
                         for key, slots in sorted(by_key.items(), key=lambda x: _key_str(x[0]))],
            "future_revisions": [
                {"rule_id": str(r.id), "number": rev.number,
                 "effective_from": rev.effective_from.isoformat(),
                 "supersedes_future": rev.supersedes_future}
                for r in rules for rev in r.revisions if rev.effective_from > effect
                and rev.scope_id == scope_id
            ],
        }


def preview_weekly(uow: UnitOfWork, owner: str, draft: WeeklyDraft):
    with uow:
        return _plan(uow, owner, draft)[0]


def confirm_weekly(uow: UnitOfWork, owner: str, draft: WeeklyDraft, *,
                   command_id: UUID, fingerprint: str, confirmed: bool,
                   acknowledge_conflicts: bool):
    if not confirmed:
        raise ValueError("explicit confirmation is required")
    payload_hash = _digest({"draft": asdict(draft),
                            "acknowledge_conflicts": acknowledge_conflicts})
    with uow:
        uow.lock_planning()  # before reading versions or any other planning state
        receipt = uow.weekly_commands.get(owner, command_id)
        if receipt is not None:
            if receipt.payload_hash != payload_hash:
                raise RuleConflict("command_id reused with different weekly edit content")
            return receipt.result
        preview, affected, children, additions, changed_exceptions = _plan(uow, owner, draft)
        if preview["fingerprint"] != fingerprint:
            raise RuleConflict("weekly preview is stale; preview again")
        if preview["unresolved_exceptions"]:
            raise ValueError("resolve future exceptions explicitly before saving")
        if preview["invalid_conflicts"]:
            raise ValueError("weekly edit creates invalid category/envelope conflicts")
        if preview["civil_time_issues"]:
            raise ValueError("weekly schedule contains invalid or ambiguous civil-time occurrences")
        if any(c["new"] for c in preview["booking_conflicts"]) and not acknowledge_conflicts:
            raise ValueError("acknowledge new booking conflicts before confirmation")
        correlation = uuid4()
        for ident, (rule, terminal) in affected.items():
            uow.recurring_availability.append_revision(terminal, expected_version=rule.version)
            uow.history.append(_event(ident, "AVAILABILITY_RULE",
                                     "AVAILABILITY_RULE_CHANGED", correlation,
                                     {"action": "CUTOVER", "at": draft.effective_from.isoformat(),
                                      "previous_version": rule.version}))
        for ident, (rule, parent) in (*children.items(), *additions.items()):
            uow.recurring_availability.add(rule)
            # First revision inserted by add(); append subsequent immutable
            # future revisions within the exact same transaction.
            for later in rule.revisions[1:]:
                uow.recurring_availability.append_revision(
                    later, expected_version=later.number - 1)
            uow.history.append(_event(ident, "AVAILABILITY_RULE",
                                     "AVAILABILITY_RULE_CREATED", correlation,
                                     {"action": "DERIVED" if parent else "REPLACEMENT",
                                      "parent_id": str(parent) if parent else None,
                                      "at": draft.effective_from.isoformat()}))
        for ident, value in changed_exceptions.items():
            uow.availability_exceptions.save(value, expected_version=value.version-1)
            uow.history.append(_event(ident, "AVAILABILITY_EXCEPTION",
                                     "AVAILABILITY_EXCEPTION_APPLIED", correlation,
                                     {"action": "REMAP" if value.enabled else "DISABLE",
                                      "rule_id": str(value.rule_id) if value.rule_id else None,
                                      "version": value.version}))
        result = {"command_id": str(command_id), "correlation_id": str(correlation)
                  if preview["has_changes"] else None,
                  "applied": preview["has_changes"], "calendar_written": False,
                  "fingerprint": fingerprint, "changes": preview["changed_sections"],
                  "open_booking_conflicts": preview["booking_conflicts"]}
        uow.weekly_commands.add(owner, command_id, payload_hash, result)
        uow.commit()
        return result
