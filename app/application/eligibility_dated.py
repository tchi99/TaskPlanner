"""TP-027A: preview/confirm for a dated permission REMOVE or MOVE.

An occurrence is a permission, never a booking or physical availability.
The original (series, local date) identity cannot be changed by a revision.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.effective_availability import _state
from app.application.eligibility_edits import _digest, _event, _projection
from app.application.eligibility_targeted import _active, _new_structural
from app.application.uow import UnitOfWork
from app.domain.eligibility import EligibilityAction, EligibilityConflict, EligibilityException
from app.domain.recurring_availability import RuleConflict
from app.domain.schedule_scopes import compatibility_scope_id

ALGORITHM = "TP-027A/dated-permission-v1"


@dataclass(frozen=True)
class DatedPermissionDraft:
    draft_id: UUID
    series_id: UUID
    exception_id: UUID | None
    expected_version: int
    original_local_date: date
    timezone_name: str
    action: EligibilityAction
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool = True


def _plan(uow: UnitOfWork, owner: str, draft: DatedPermissionDraft):
    series = uow.eligibility.get(draft.series_id, owner)
    if series is None:
        raise LookupError("permission series not found")
    try:
        zone = ZoneInfo(draft.timezone_name)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    if draft.original_local_date < datetime.now(zone).date():
        raise ValueError("dated permission edits cannot rewrite the past")
    source = _active(series, draft.original_local_date)
    if source is None:
        raise ValueError("original permission occurrence is not active")
    if draft.timezone_name != source.timezone_name:
        raise ValueError("dated permission timezone must match the source series")
    if draft.action is EligibilityAction.MOVE:
        if draft.starts_at is None or draft.ends_at is None:
            raise ValueError("MOVE needs offset-aware start and end instants")
        if (draft.starts_at.tzinfo is None or draft.starts_at.utcoffset() is None
                or draft.ends_at.tzinfo is None or draft.ends_at.utcoffset() is None):
            raise ValueError("MOVE instants must include explicit offsets")
        # Offset-aware input is not sufficient by itself: 02:30-05:00 on
        # Toronto's spring-forward day denotes 03:30 local, not 02:30.
        for instant in (draft.starts_at, draft.ends_at):
            local = instant.astimezone(zone)
            if (local.date(), local.hour, local.minute, local.utcoffset()) != (
                    instant.date(), instant.hour, instant.minute, instant.utcoffset()):
                raise ValueError("MOVE instant has a non-existent or mismatched local time/offset")
        if draft.starts_at.astimezone(zone).date() < datetime.now(zone).date():
            raise ValueError("MOVE target cannot be in the past")
        if abs((draft.starts_at.astimezone(zone).date() - draft.original_local_date).days) > 92:
            raise ValueError("MOVE must remain within the 93-day verification window")
    old = uow.eligibility.get_exception(draft.exception_id, owner) if draft.exception_id else None
    existing = tuple(uow.eligibility.list_exceptions(owner))
    if draft.exception_id:
        if (old is None or old.series_id != series.id
                or old.original_local_date != draft.original_local_date):
            raise ValueError("exception identity and original date are immutable")
        if old.version != draft.expected_version:
            raise EligibilityConflict("permission exception changed; preview again")
    elif draft.expected_version != 0:
        raise ValueError("new dated permission requires expected_version 0")
    if old is None and not draft.enabled:
        raise ValueError("cannot disable an exception that does not exist")
    if old is None and any(item.enabled and item.series_id == series.id
                           and item.original_local_date == draft.original_local_date
                           for item in existing):
        raise EligibilityConflict("dated permission already has an exception")
    ident = old.id if old else uuid5(
        NAMESPACE_URL, f"tp027a:dated:{owner}:{draft.draft_id}:{series.id}:{draft.original_local_date}")
    if old is None and uow.eligibility.get_exception(ident, owner):
        raise EligibilityConflict("dated permission draft already committed")
    proposed = EligibilityException(
        ident, owner, series.id, draft.original_local_date,
        old.version + 1 if old else 1, draft.action, draft.timezone_name,
        draft.starts_at, draft.ends_at, draft.enabled,
    )
    revised = tuple(proposed if item.id == ident else item for item in existing)
    if old is None:
        revised += (proposed,)
    start = min(draft.original_local_date,
                draft.starts_at.astimezone(zone).date()
                if draft.starts_at is not None else draft.original_local_date)
    end = start + timedelta(days=93)
    rules, physical_exceptions, manual, confirmed = _state(uow, owner, start, end)
    all_bookings = tuple(uow.time_blocks.list_all_confirmed())
    scopes = tuple(uow.schedule_scopes.list_owner(owner))
    affiliations = tuple(uow.schedule_scopes.affiliations(owner))
    permission_series = tuple(uow.eligibility.list_owner(owner))
    compat = compatibility_scope_id(owner)
    before = _projection(rules, physical_exceptions, manual, confirmed, permission_series,
                         existing, start, end, draft.timezone_name, compat, affiliations)
    after = _projection(rules, physical_exceptions, manual, confirmed, permission_series,
                        revised, start, end, draft.timezone_name, compat, affiliations)
    old_civil = {(v.code, v.series_id, v.original_local_date)
                 for v in before[1].expansion_issues}
    civil = sorted({v.code for v in after[1].expansion_issues
                    if (v.code, v.series_id, v.original_local_date) not in old_civil})
    inventory = [{
        "id": str(book.id), "starts_at": book.starts_at.isoformat(),
        "ends_at": book.ends_at.isoformat(),
    } for book in all_bookings if (book.scope_id or compat) == series.scope_id
       and book.ends_at.astimezone(zone).date() >= start
       and book.starts_at.astimezone(zone).date() < end]
    snapshot = {
        "algorithm": ALGORITHM, "draft": asdict(draft),
        "series": [asdict(item) for item in permission_series],
        "permission_exceptions": [asdict(item) for item in existing],
        "rules": [asdict(item) for item in rules],
        "physical_exceptions": [asdict(item) for item in physical_exceptions],
        "manual": [asdict(item) for item in manual],
        "bookings": [asdict(item) for item in all_bookings],
        "scopes": [asdict(item) for item in scopes],
        "affiliations": [asdict(item) for item in affiliations],
        "scope_versions": uow.schedule_scopes.versions(owner),
    }
    response = {
        "fingerprint": _digest(snapshot), "algorithm": ALGORITHM,
        "exception_id": str(ident), "series_id": str(series.id),
        "original_local_date": draft.original_local_date.isoformat(),
        "before": asdict(old) if old else None, "after": asdict(proposed),
        "blocking_issues": _new_structural(before, after) + civil,
        "booking_inventory": inventory,
        "projection_days": 93, "calendar_checked": False, "calendar_written": False,
    }
    return response, old, proposed


def preview_dated(uow: UnitOfWork, owner: str, draft: DatedPermissionDraft) -> dict:
    with uow:
        return _plan(uow, owner, draft)[0]


def confirm_dated(uow: UnitOfWork, owner: str, draft: DatedPermissionDraft, *,
                  command_id: UUID, fingerprint: str, confirmed: bool,
                  acknowledge_bookings: bool) -> dict:
    if not confirmed:
        raise ValueError("explicit confirmation required")
    payload_hash = _digest({"algorithm": ALGORITHM, "draft": asdict(draft),
                            "acknowledge_bookings": acknowledge_bookings})
    with uow:
        uow.lock_planning()
        receipt = uow.weekly_commands.get(owner, command_id)
        if receipt is not None:
            if receipt.payload_hash != payload_hash:
                raise RuleConflict("command_id reused with different permission exception content")
            return receipt.result
        preview, old, value = _plan(uow, owner, draft)
        if fingerprint != preview["fingerprint"]:
            raise RuleConflict("dated permission preview is stale; preview again")
        if preview["blocking_issues"]:
            raise ValueError("resolve dated permission conflicts before confirmation")
        if preview["booking_inventory"] and not acknowledge_bookings:
            raise ValueError("explicit acknowledgement of future bookings required")
        correlation = uuid4()
        if old is None:
            uow.eligibility.add_exception(value)
        else:
            uow.eligibility.append_exception(value, expected_version=old.version)
        uow.history.append(_event(value.series_id, correlation, "ELIGIBILITY_EXCEPTION_CHANGED", {
            "operation": "CREATE" if old is None else "REVISE",
            "exception_id": str(value.id), "series_id": str(value.series_id), "original_local_date": str(value.original_local_date),
            "version": value.version, "action": value.action.value,
        }))
        result = {"applied": True, "exception_id": str(value.id), "version": value.version,
                  "command_id": str(command_id), "correlation_id": str(correlation),
                  "calendar_written": False}
        uow.weekly_commands.add(owner, command_id, payload_hash, result)
        uow.commit()
        return result
