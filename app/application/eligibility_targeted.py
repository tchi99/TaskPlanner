"""TP-027A: scoped recurring eligibility cutover (ADR-0026 D1).

Editing selected weekdays is a replacement, not a rewrite of prior revisions.
The original series receives a terminal marker; unchanged weekdays are copied
to derived series with their own full future revision timelines.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.application.effective_availability import _state
from app.application.eligibility_edits import (
    ALGORITHM as LEGACY_ALGORITHM, _digest, _event, _projection, _validate,
)
from app.application.uow import UnitOfWork
from app.domain.eligibility import EligibilityAction, EligibilityException, EligibilityRevision, EligibilitySeries
from app.domain.recurring_availability import RuleConflict
from app.domain.schedule_scopes import compatibility_scope_id

ALGORITHM = "TP-027A/targeted-cutover-v1"
STRUCTURAL = {
    "ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE",
    "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE",
    "ELIGIBILITY_SCOPE_MISMATCH",
    "ELIGIBILITY_AFFILIATION_MISMATCH",
    "CONFLICTING_ELIGIBILITY_RANKS",
}


def _active(series: EligibilitySeries, day: date) -> EligibilityRevision | None:
    revisions = [rev for rev in series.revisions if rev.effective_from <= day]
    if not revisions or any(rev.supersedes_future for rev in revisions):
        return None
    rev = max(revisions, key=lambda row: (row.effective_from, row.number))
    if not rev.enabled or (rev.valid_until is not None and day >= rev.valid_until):
        return None
    return rev if day.weekday() in rev.days_of_week else None


def _child(source: EligibilitySeries, weekday: int, effect: date, identity: UUID) -> EligibilitySeries | None:
    milestones = {effect}
    for rev in source.revisions:
        if rev.effective_from > effect:
            milestones.add(rev.effective_from)
        if rev.valid_until is not None and rev.valid_until > effect:
            milestones.add(rev.valid_until)
    revisions: list[EligibilityRevision] = []
    previous = None
    for when in sorted(milestones):
        active = _active(source, when) if when.weekday() == weekday else None
        # A revision's weekday applies to the next occurrence, not necessarily
        # the weekday of its effective_from date.
        if when.weekday() != weekday:
            probe = when + timedelta(days=(weekday - when.weekday()) % 7)
            active = _active(source, probe)
        else:
            probe = when
        state = None if active is None else (
            active.timezone_name, active.starts_at_local, active.ends_at_local,
            active.priority_rank, active.start_fold, active.end_fold,
        )
        if state == previous:
            continue
        if state is not None:
            revisions.append(EligibilityRevision(
                identity, len(revisions) + 1, when, None,
                state[0], (weekday,), state[1], state[2], state[3], True,
                state[4], state[5],
            ))
        elif revisions:
            last = revisions[-1]
            revisions.append(replace(
                last, number=len(revisions) + 1, effective_from=when,
                enabled=False, valid_until=None,
            ))
        previous = state
    return EligibilitySeries(identity, source.owner_id, source.scope_id,
                             source.work_type_id, len(revisions), tuple(revisions)) if revisions else None


def _new_structural(before, after) -> list[str]:
    """Compare covered UTC minutes, not fragment identities or new series IDs."""
    old = {}
    for issue in before[1].issues:
        if issue.code in STRUCTURAL:
            old.setdefault((issue.code, tuple(issue.scope_ids)), []).append(
                (issue.starts_at, issue.ends_at))
    new_codes = set()
    for issue in after[1].issues:
        if issue.code not in STRUCTURAL:
            continue
        spans = old.get((issue.code, tuple(issue.scope_ids)), ())
        if not any(lo <= issue.starts_at and hi >= issue.ends_at for lo, hi in spans):
            new_codes.add(issue.code)
    return sorted(new_codes)


def _plan(uow: UnitOfWork, owner: str, draft):
    current, _ = _validate(uow, owner, draft)
    if current is None or not draft.target_days_of_week:
        raise ValueError("a saved series and explicit target weekdays are required")
    selected = set(draft.target_days_of_week)
    if (tuple(sorted(selected)) != draft.target_days_of_week
            or any(type(day) is not int or not 0 <= day <= 6 for day in selected)):
        raise ValueError("target weekdays must be sorted, unique and in 0..6")
    available = {day for rev in current.revisions for day in rev.days_of_week}
    if not selected <= available:
        raise ValueError("target weekday does not belong to the source series")
    # Dragging a bar must not quietly change the source series time zone.
    if draft.timezone_name != current.revisions[-1].timezone_name:
        raise ValueError("editing a series in a different timezone requires a separate explicit operation")
    if not draft.enabled and set(draft.days_of_week) != selected:
        raise ValueError("disabled replacement must retain the selected weekdays")
    if not draft.enabled:
        replacement = None
    else:
        new_id = uuid5(NAMESPACE_URL, f"tp027a:{owner}:{draft.draft_id}:{current.id}:replacement")
        if uow.eligibility.get(new_id, owner):
            raise RuleConflict("draft was already saved; reopen the editor")
        replacement = EligibilitySeries(
            new_id, owner, current.scope_id, current.work_type_id, 1,
            (EligibilityRevision(
                new_id, 1, draft.effective_from, None, draft.timezone_name,
                draft.days_of_week, draft.starts_at_local, draft.ends_at_local,
                draft.priority_rank, True, draft.start_fold, draft.end_fold,
            ),),
        )
    terminal = replace(current.revisions[-1], number=current.version + 1,
                       effective_from=draft.effective_from, valid_until=None,
                       enabled=False, supersedes_future=True)
    terminated = EligibilitySeries(
        current.id, owner, current.scope_id, current.work_type_id,
        current.version + 1, current.revisions + (terminal,),
    )
    children = {}
    for weekday in sorted(available - selected):
        ident = uuid5(NAMESPACE_URL, f"tp027a:{owner}:{draft.draft_id}:{current.id}:day:{weekday}")
        if uow.eligibility.get(ident, owner):
            raise RuleConflict("derived series already saved; reopen the editor")
        child = _child(current, weekday, draft.effective_from, ident)
        if child:
            children[weekday] = child
    series = tuple(uow.eligibility.list_owner(owner))
    old_exceptions = tuple(uow.eligibility.list_exceptions(owner))
    decisions = {decision.exception_id: decision for decision in draft.exception_decisions}
    if len(decisions) != len(draft.exception_decisions):
        raise ValueError("duplicate exception decision")
    revised_exceptions = []
    successors = []
    changes = []
    touched = set()
    unresolved = []
    for exc in old_exceptions:
        if not exc.enabled or exc.series_id != current.id or exc.original_local_date < draft.effective_from:
            revised_exceptions.append(exc)
            continue
        day = exc.original_local_date.weekday()
        decision = decisions.get(exc.id)
        if decision and (decision.expected_version != exc.version
                         or decision.action not in ("KEEP", "REPLACE", "DISABLE")):
            raise RuleConflict("exception changed or unsupported resolution")
        target = replacement if day in selected else children.get(day)
        # An affected weekday requires an explicit decision, even when it is
        # possible to preserve the exception on the replacement occurrence.
        if day in selected and decision is None:
            unresolved.append({"exception_id": str(exc.id), "expected_version": exc.version,
                               "choices": ["KEEP", "REPLACE", "DISABLE"] if target else ["DISABLE"]})
        if day not in selected and decision is not None:
            raise ValueError("unselected weekday exceptions are preserved automatically")
        action = decision.action if decision else ("DISABLE" if day in selected else "KEEP")
        if action in ("KEEP", "REPLACE") and (
                target is None or _active(target, exc.original_local_date) is None):
            raise ValueError("exception cannot be preserved without a target occurrence")
        if decision is not None:
            if action == "REPLACE" and decision.replacement_action is None:
                raise ValueError("REPLACE must specify replacement_action")
            if action != "REPLACE" and (decision.replacement_action is not None
                                       or decision.starts_at is not None or decision.ends_at is not None):
                raise ValueError("only REPLACE can supply replacement fields")
        touched.add(exc.id)
        revised_exceptions.append(replace(exc, version=exc.version + 1, enabled=False))
        successor_id = None
        if action in ("KEEP", "REPLACE"):
            successor_id = uuid5(NAMESPACE_URL, f"tp027a:{draft.draft_id}:exception:{exc.id}:{target.id}")
            successors.append(EligibilityException(
                successor_id, owner, target.id, exc.original_local_date, 1,
                decision.replacement_action if action == "REPLACE" else exc.action,
                exc.timezone_name,
                decision.starts_at if action == "REPLACE" else exc.starts_at,
                decision.ends_at if action == "REPLACE" else exc.ends_at,
                True,
            ))
        changes.append({"exception_id": str(exc.id), "action": action,
                        "successor_id": str(successor_id) if successor_id else None})
    if set(decisions) != touched & set(decisions):
        raise ValueError("exception decisions must refer to affected, owned exceptions")
    new_series = tuple(item for item in series if item.id != current.id) + (terminated,)
    new_series += tuple(children.values())
    if replacement:
        new_series += (replacement,)
    new_exceptions = tuple(revised_exceptions) + tuple(successors)
    start = draft.effective_from
    end = start + timedelta(days=93)
    rules, physical_exceptions, manual, confirmed = _state(uow, owner, start, end)
    bookings = tuple(uow.time_blocks.list_all_confirmed())
    affiliations = tuple(uow.schedule_scopes.affiliations(owner))
    compat = compatibility_scope_id(owner)
    before = _projection(rules, physical_exceptions, manual, confirmed, series,
                         old_exceptions, start, end, draft.timezone_name, compat, affiliations)
    after = _projection(rules, physical_exceptions, manual, confirmed, new_series,
                        new_exceptions, start, end, draft.timezone_name, compat, affiliations)
    invalid = _new_structural(before, after)
    old_civil = {(v.code, v.series_id, v.original_local_date)
                 for v in before[1].expansion_issues}
    civil = sorted({v.code for v in after[1].expansion_issues
                    if (v.code, v.series_id, v.original_local_date) not in old_civil})
    inventory = []
    zone = ZoneInfo(draft.timezone_name)
    for booking in bookings:
        if (booking.scope_id or compat) != draft.scope_id:
            continue
        if booking.ends_at.astimezone(zone).date() < start:
            continue
        inventory.append({"id": str(booking.id), "starts_at": booking.starts_at.isoformat(),
                          "ends_at": booking.ends_at.isoformat()})
    snapshot = {
        "algorithm": ALGORITHM, "draft": asdict(draft),
        "rules": [asdict(v) for v in rules], "physical_exceptions": [asdict(v) for v in physical_exceptions],
        "manual": [asdict(v) for v in manual], "bookings": [asdict(v) for v in bookings],
        "series": [asdict(v) for v in series], "exceptions": [asdict(v) for v in old_exceptions],
        "scopes": [asdict(v) for v in uow.schedule_scopes.list_owner(owner)],
        "affiliations": [asdict(v) for v in affiliations],
        "scope_versions": uow.schedule_scopes.versions(owner),
    }
    response = {
        "algorithm": ALGORITHM, "fingerprint": _digest(snapshot),
        "series_id": str(replacement.id) if replacement else None,
        "source_series_id": str(current.id), "source_version": current.version,
        "target_days_of_week": draft.target_days_of_week,
        "future_revisions_superseded": [
            rev.number for rev in current.revisions if rev.effective_from >= start],
        "preserved_weekday_series": {str(day): str(child.id) for day, child in children.items()},
        "exception_decisions": changes, "unresolved_exceptions": unresolved,
        "before_physical_minutes": before[1].physical_minutes,
        "after_physical_minutes": after[1].physical_minutes,
        "booking_inventory": inventory,
        "blocking_issues": invalid + civil + (["UNRESOLVED_ELIGIBILITY_EXCEPTIONS"] if unresolved else []),
        "projection_days": 93, "calendar_checked": False, "calendar_written": False,
        "consequences": ["Targeted future occurrences are replaced atomically.",
                         "Unselected future weekday revisions remain traceable.",
                         "Confirmed bookings and Google Calendar are never changed."],
    }
    return response, current, terminated, children, replacement, old_exceptions, revised_exceptions, successors


def preview_targeted(uow: UnitOfWork, owner: str, draft) -> dict:
    with uow:
        return _plan(uow, owner, draft)[0]


def confirm_targeted(uow: UnitOfWork, owner: str, draft, *,
                     command_id: UUID, fingerprint: str, confirmed: bool,
                     acknowledge_bookings: bool) -> dict:
    if not confirmed:
        raise ValueError("explicit confirmation required")
    payload_hash = _digest({"algorithm": ALGORITHM, "draft": asdict(draft),
                            "acknowledge_bookings": acknowledge_bookings})
    with uow:
        uow.lock_planning()
        receipt = uow.weekly_commands.get(owner, command_id)
        if receipt:
            if receipt.payload_hash != payload_hash:
                raise RuleConflict("command_id reused with different eligibility content")
            return receipt.result
        (preview, current, terminated, children, replacement, old_exceptions,
         revised_exceptions, successors) = _plan(uow, owner, draft)
        if preview["fingerprint"] != fingerprint:
            raise RuleConflict("eligibility preview is stale; preview again")
        if preview["blocking_issues"]:
            raise ValueError("resolve eligibility conflicts before confirmation")
        if preview["booking_inventory"] and not acknowledge_bookings:
            raise ValueError("explicit acknowledgement of future bookings is required")
        correlation = uuid4()
        uow.eligibility.append_revision(owner, terminated.revisions[-1],
                                        expected_version=current.version)
        for child in children.values():
            uow.eligibility.add(EligibilitySeries(
                child.id, child.owner_id, child.scope_id, child.work_type_id, 1,
                child.revisions[:1],
            ))
            for revision in child.revisions[1:]:
                uow.eligibility.append_revision(owner, revision,
                                                expected_version=revision.number - 1)
            uow.history.append(_event(child.id, correlation, "ELIGIBILITY_SERIES_DERIVED",
                                      {"from_series_id": str(current.id),
                                       "weekday": child.revisions[0].days_of_week[0]}))
        if replacement:
            uow.eligibility.add(replacement)
        for old, new in zip(old_exceptions, revised_exceptions):
            if new.version > old.version:
                uow.eligibility.append_exception(new, expected_version=old.version)
                uow.history.append(_event(old.series_id, correlation, "ELIGIBILITY_EXCEPTION_DISABLED",
                                          {"exception_id": str(old.id), "version": new.version}))
        successor_sources = {
            change["successor_id"]: change["exception_id"]
            for change in preview["exception_decisions"] if change["successor_id"]
        }
        for successor in successors:
            uow.eligibility.add_exception(successor)
            uow.history.append(_event(successor.series_id, correlation, "ELIGIBILITY_EXCEPTION_DERIVED",
                                      {"exception_id": str(successor.id),
                                       "source_exception_id": successor_sources[str(successor.id)],
                                       "series_id": str(successor.series_id)}))
        uow.history.append(_event(current.id, correlation, "ELIGIBILITY_SERIES_CHANGED",
                                  {"operation": "TARGETED_CUTOVER",
                                   "target_days": list(draft.target_days_of_week),
                                   "effective_from": str(draft.effective_from),
                                   "replacement_id": str(replacement.id) if replacement else None}))
        result = {"applied": True, "series_id": preview["series_id"],
                  "source_series_id": str(current.id),
                  "command_id": str(command_id), "correlation_id": str(correlation),
                  "calendar_written": False}
        uow.weekly_commands.add(owner, command_id, payload_hash, result)
        uow.commit()
        return result
