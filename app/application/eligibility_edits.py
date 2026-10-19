"""TP-025D: explicit, versioned edits of nonexclusive eligibility.

All calculations reuse the authoritative physical and eligibility projectors.
Neither preview nor confirm touches confirmed bookings or Google Calendar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.effective_availability import _state
from app.application.history import HistoryEvent, HistorySource
from app.application.uow import UnitOfWork
from app.domain.effective_availability import project_effective
from app.domain.eligibility import (
    EligibilityConflict, EligibilityRevision, EligibilitySeries,
)
from app.domain.eligibility_projection import project_eligibility, reconcile_booking_issues
from app.domain.recurring_availability import (
    AvailabilityMode, RecurringAvailabilityRule, RuleConflict, RuleKind,
)
from app.domain.schedule_scopes import compatibility_scope_id, effective_scope

ALGORITHM = "TP-025D/contextual-edit-v1"
_BLOCKING = {
    "ELIGIBILITY_OUTSIDE_PHYSICAL_ENVELOPE",
    "ELIGIBILITY_OVER_LEGACY_EXCLUSIVE",
    "ELIGIBILITY_SCOPE_MISMATCH",
    "ELIGIBILITY_AFFILIATION_MISMATCH",
    "CONFLICTING_ELIGIBILITY_RANKS",
    "INCOMPATIBLE_SCOPES",
    "INCOMPATIBLE_WORK_TYPES",
    "INCOMPATIBLE_MODES",
    "OUTSIDE_GENERAL_ENVELOPE",
}


@dataclass(frozen=True)
class EligibilityDraft:
    draft_id: UUID
    series_id: UUID | None
    legacy_rule_id: UUID | None
    scope_id: UUID
    work_type_id: UUID
    expected_version: int  # zero for new series
    expected_legacy_version: int | None
    effective_from: date
    timezone_name: str
    days_of_week: tuple[int, ...]
    starts_at_local: str
    ends_at_local: str
    priority_rank: int | None
    enabled: bool
    start_fold: int | None = None
    end_fold: int | None = None


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=True,
                             separators=(",", ":")).encode()).hexdigest()


def _event(identifier: UUID, correlation: UUID, action: str, detail: dict, *,
           entity_type: str = "ELIGIBILITY_SERIES") -> HistoryEvent:
    now = datetime.now(ZoneInfo("UTC"))
    return HistoryEvent(
        id=uuid4(), occurred_at=now, recorded_at=now, entity_type=entity_type,
        entity_id=identifier, task_id=None, event_type=action, schema_version=1,
        source=HistorySource.USER, reason_code=None, correlation_id=correlation,
        causation_id=None, payload=detail,
    )


def read_series(uow: UnitOfWork, owner: str, identifier: UUID) -> dict:
    with uow:
        series = uow.eligibility.get(identifier, owner)
        if series is None:
            raise LookupError("eligibility series not found")
        return asdict(series)


def _validate(uow: UnitOfWork, owner: str, draft: EligibilityDraft):
    if draft.legacy_rule_id is not None or draft.expected_legacy_version is not None:
        raise ValueError("legacy rule conversion is not supported by TP-026")
    try:
        zone = ZoneInfo(draft.timezone_name)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    if draft.effective_from <= datetime.now(zone).date():
        raise ValueError("changes must start on a future local date")
    if uow.work_types.get(draft.work_type_id) is None:
        raise ValueError("work type not found")
    scope = uow.schedule_scopes.get(owner, draft.scope_id)
    if scope is None or scope.state != "ACTIVE":
        raise ValueError("scope not owned or inactive")
    if effective_scope(draft.work_type_id, draft.effective_from,
                       uow.schedule_scopes.affiliations(owner),
                       compatibility_scope_id(owner)) != draft.scope_id:
        raise ValueError("work type does not belong to this parent at the effective date")
    # Domain validation also covers ordered weekdays, HH:MM, ranks and folds.
    new_id = draft.series_id or uuid5(NAMESPACE_URL, f"eligibility:{owner}:{draft.draft_id}")
    if draft.series_id is None and uow.eligibility.get(new_id, owner) is not None:
        raise EligibilityConflict("eligibility draft identity already saved; reopen the editor")
    current = None
    if draft.series_id is not None:
        current = uow.eligibility.get(draft.series_id, owner)
        if current is None:
            raise LookupError("eligibility series not found")
        if current.version != draft.expected_version:
            raise EligibilityConflict("eligibility series version changed; preview again")
        if current.scope_id != draft.scope_id or current.work_type_id != draft.work_type_id:
            raise ValueError("series parent and work type cannot be changed")
    elif draft.expected_version != 0:
        raise ValueError("new eligibility series requires expected_version 0")
    legacy = None
    if draft.legacy_rule_id is not None:
        legacy = uow.recurring_availability.get(draft.legacy_rule_id, owner)
        if legacy is None:
            raise LookupError("legacy series not found")
        if legacy.version != draft.expected_legacy_version:
            raise RuleConflict("legacy rule version changed; preview again")
        active = [r for r in legacy.revisions if r.effective_from <= draft.effective_from]
        if not active or any(r.supersedes_future for r in active):
            raise ValueError("legacy series is inactive at cutover")
        rev = max(active, key=lambda r: (r.effective_from, r.number))
        if (not rev.enabled
                or (rev.valid_until is not None and draft.effective_from >= rev.valid_until)
                or rev.kind is not RuleKind.CATEGORIZED
                or rev.mode is not AvailabilityMode.PREFERRED
                or rev.work_type_id != draft.work_type_id
                or (rev.scope_id or compatibility_scope_id(owner)) != draft.scope_id):
            raise ValueError("only matching exclusive PREFERRED rules can opt in; PROTECTED is never converted")
    number = current.version + 1 if current else 1
    revision = EligibilityRevision(
        new_id, number, draft.effective_from, None, draft.timezone_name,
        draft.days_of_week, draft.starts_at_local, draft.ends_at_local,
        draft.priority_rank, draft.enabled, draft.start_fold, draft.end_fold,
    )
    series = EligibilitySeries(new_id, owner, draft.scope_id, draft.work_type_id,
                               number, (*current.revisions, revision) if current else (revision,))
    return current, series, legacy


def _projection(rules, exceptions, manual, confirmed, series, permission_exceptions,
                start, end, zone, compatibility, affiliations):
    physical = project_effective(
        rules, exceptions, manual, confirmed, start, end, zone,
        compatibility_id=compatibility, affiliations=affiliations)
    eligibility = project_eligibility(
        physical, series, permission_exceptions, start, end, zone,
        compatibility_id=compatibility, affiliations=affiliations)
    return reconcile_booking_issues(physical, eligibility, confirmed, compatibility)


def _issue_identity(issue):
    return (issue.code, issue.starts_at, issue.ends_at, tuple(issue.scope_ids))


def _plan(uow: UnitOfWork, owner: str, draft: EligibilityDraft):
    existing, edited, legacy = _validate(uow, owner, draft)
    start, end = draft.effective_from, draft.effective_from + timedelta(days=93)
    rules, exceptions, manual, confirmed = _state(uow, owner, start, end)
    all_bookings = tuple(uow.time_blocks.list_all_confirmed())
    series = tuple(uow.eligibility.list_owner(owner))
    permission_exceptions = tuple(uow.eligibility.list_exceptions(owner))
    affiliations = tuple(uow.schedule_scopes.affiliations(owner))
    scopes = tuple(uow.schedule_scopes.list_owner(owner))
    compat = compatibility_scope_id(owner)
    future_legacy_exceptions = [
        e for e in exceptions if legacy is not None and e.enabled
        and e.rule_id == legacy.id and e.original_local_date is not None
        and e.original_local_date >= draft.effective_from
    ]
    future_permission_exceptions = [
        e for e in permission_exceptions if existing is not None and e.enabled
        and e.series_id == existing.id and e.original_local_date >= draft.effective_from
    ]
    revised_rules = rules
    terminal = None
    if legacy is not None:
        terminal = replace(legacy.revisions[-1], number=legacy.version + 1,
                           effective_from=draft.effective_from, valid_until=None,
                           enabled=False, supersedes_future=True)
        revised_rules = tuple(
            RecurringAvailabilityRule(r.id, r.owner_id, r.version + 1,
                                      (*r.revisions, terminal)) if r.id == legacy.id else r
            for r in rules
        )
    revised_series = tuple(v for v in series if v.id != edited.id) if existing else series
    revised_series += (edited,)
    before = _projection(rules, exceptions, manual, confirmed, series,
                         permission_exceptions, start, end, draft.timezone_name,
                         compat, affiliations)
    after = _projection(revised_rules, exceptions, manual, confirmed, revised_series,
                        permission_exceptions, start, end, draft.timezone_name,
                        compat, affiliations)
    previous = {_issue_identity(issue) for projection in before for issue in projection.issues}
    new_issues = sorted({
        issue.code for projection in after for issue in projection.issues
        if issue.code in _BLOCKING and _issue_identity(issue) not in previous
    })
    before_civil = {(v.code, v.series_id, v.original_local_date)
                    for v in before[1].expansion_issues}
    new_civil = sorted({
        v.code for v in after[1].expansion_issues
        if (v.code, v.series_id, v.original_local_date) not in before_civil
    })
    # Booking inventory includes persisted future reservations beyond the 93-day
    # projection horizon. No booking may be moved or silently deleted.
    inventory = [{
        "id": str(b.id), "starts_at": b.starts_at.isoformat(),
        "ends_at": b.ends_at.isoformat(),
    } for b in all_bookings if b.starts_at.astimezone(ZoneInfo(draft.timezone_name)).date() >= draft.effective_from
       and (b.scope_id or compat) == draft.scope_id]
    blocked = list(new_issues) + list(new_civil)
    if future_legacy_exceptions:
        blocked.append("UNRESOLVED_LEGACY_EXCEPTIONS")
    if future_permission_exceptions:
        blocked.append("UNRESOLVED_ELIGIBILITY_EXCEPTIONS")
    state = {
        "algorithm": ALGORITHM, "draft": asdict(draft),
        "rules": [asdict(v) for v in rules],
        "exceptions": [asdict(v) for v in exceptions],
        "series": [asdict(v) for v in series],
        "permission_exceptions": [asdict(v) for v in permission_exceptions],
        "manual": [asdict(v) for v in manual],
        "bookings": [asdict(v) for v in all_bookings],
        "scopes": [asdict(v) for v in scopes],
        "scope_versions": uow.schedule_scopes.versions(owner),
        "affiliations": [asdict(v) for v in affiliations],
    }
    output = {
        "fingerprint": _digest(state), "series_id": str(edited.id),
        "blocking_issues": blocked, "booking_inventory": inventory,
        "before_physical_minutes": before[1].physical_minutes,
        "after_physical_minutes": after[1].physical_minutes,
        "potential_minutes": [{"work_type_id": str(t), "minutes": m,
                                "non_additive": True}
                               for t, m in after[1].potential_minutes],
        "calendar_checked": False, "calendar_written": False,
        "projection_days": 93,
        "consequences": [
            "Édition future seulement : les anciennes révisions restent conservées.",
            "Les minutes superposées restent une capacité physique unique.",
            "Aucune réservation locale confirmée n'est déplacée ou supprimée.",
            "Google Calendar reste non vérifié et en lecture seule.",
        ],
    }
    return output, existing, edited, legacy, terminal


def preview_edit(uow: UnitOfWork, owner: str, draft: EligibilityDraft) -> dict:
    with uow:
        return _plan(uow, owner, draft)[0]


def confirm_edit(uow: UnitOfWork, owner: str, draft: EligibilityDraft, *,
                 command_id: UUID, fingerprint: str, confirmed: bool,
                 acknowledge_bookings: bool) -> dict:
    if not confirmed:
        raise ValueError("explicit confirmation required")
    payload_hash = _digest({"action": ALGORITHM, "draft": asdict(draft),
                            "acknowledge_bookings": acknowledge_bookings})
    with uow:
        uow.lock_planning()
        receipt = uow.weekly_commands.get(owner, command_id)
        if receipt:
            if receipt.payload_hash != payload_hash:
                raise RuleConflict("command_id reused with different eligibility content")
            return receipt.result
        preview, existing, edited, legacy, terminal = _plan(uow, owner, draft)
        if preview["fingerprint"] != fingerprint:
            raise RuleConflict("eligibility preview is stale; preview again")
        if preview["blocking_issues"]:
            raise ValueError("resolve eligibility conflicts before confirmation")
        if preview["booking_inventory"] and not acknowledge_bookings:
            raise ValueError("explicit acknowledgement of future bookings is required")
        correlation = uuid4()
        if legacy is not None:
            assert terminal is not None
            uow.recurring_availability.append_revision(
                terminal, expected_version=legacy.version)
            uow.history.append(_event(legacy.id, correlation, "AVAILABILITY_RULE_CHANGED",
                {"operation": "EXPLICIT_SHARED_CUTOVER", "effective_from": str(draft.effective_from),
                 "preserved_legacy_mode": "PREFERRED"}, entity_type="AVAILABILITY_RULE"))
        if existing is None:
            uow.eligibility.add(edited)
        else:
            uow.eligibility.append_revision(owner, edited.revisions[-1],
                                             expected_version=existing.version)
        uow.history.append(_event(edited.id, correlation, "ELIGIBILITY_SERIES_CHANGED",
            {"operation": "CUTOVER" if legacy else "REVISE" if existing else "CREATE",
             "version": edited.version, "effective_from": str(draft.effective_from),
             "priority_rank": draft.priority_rank, "scope_id": str(draft.scope_id),
             "legacy_rule_id": str(legacy.id) if legacy else None}))
        result = {"applied": True, "series_id": str(edited.id), "calendar_written": False,
                  "correlation_id": str(correlation), "command_id": str(command_id)}
        uow.weekly_commands.add(owner, command_id, payload_hash, result)
        uow.commit()
        return result
