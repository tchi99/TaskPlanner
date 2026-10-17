"""TP-022B read/preview/confirm boundary; never mutates confirmed bookings."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.application.history import HistoryEvent, HistorySource
from app.application.uow import UnitOfWork
from app.domain.availability_exceptions import AvailabilityException, ExceptionAction
from app.domain.effective_availability import EffectiveProjection, project_effective
from app.domain.eligibility_projection import project_eligibility, reconcile_booking_issues
from app.domain.recurring_availability import RuleConflict, expand_rules
from app.domain.schedule_scopes import compatibility_scope_id, effective_scope


def _weeks(start: date, end: date):
    # Include the adjacent week: stored manual/confirmed blocks may carry
    # an explicit offset different from the requested IANA zone.
    current = start - timedelta(days=start.weekday() + 7)
    limit = end + timedelta(days=7)
    while current < limit:
        yield current
        current += timedelta(days=7)


def _state(uow: UnitOfWork, owner_id: str, start: date, end: date):
    rules = tuple(uow.recurring_availability.list_owner(owner_id))
    exceptions = tuple(uow.availability_exceptions.list_owner(owner_id))
    manual = tuple(block for week in _weeks(start, end)
                   for block in uow.availability.list_week(week))
    confirmed = tuple(block for week in _weeks(start, end)
                      for block in uow.time_blocks.list_week(week))
    return rules, exceptions, manual, confirmed


def read_effective(
    uow: UnitOfWork, owner_id: str, start: date, end: date, timezone_name: str,
) -> EffectiveProjection:
    if not 0 < (end - start).days <= 93:
        raise ValueError("projection requires 1 to 93 days")
    with uow:
        rules, exceptions, manual, confirmed = _state(uow, owner_id, start, end)
        compatibility = compatibility_scope_id(owner_id)
        affiliations = uow.schedule_scopes.affiliations(owner_id)
        physical = project_effective(
            rules, exceptions, manual, confirmed, start, end, timezone_name,
            compatibility_id=compatibility, affiliations=affiliations,
        )
        eligibility = project_eligibility(
            physical, tuple(uow.eligibility.list_owner(owner_id)),
            tuple(uow.eligibility.list_exceptions(owner_id)), start, end,
            timezone_name, compatibility_id=compatibility,
            affiliations=affiliations,
        )
        return reconcile_booking_issues(physical, eligibility, confirmed,
                                        compatibility)[0]


def list_exceptions(uow: UnitOfWork, owner_id: str):
    with uow:
        return tuple(uow.availability_exceptions.list_owner(owner_id))


def get_exception(uow: UnitOfWork, owner_id: str, exception_id: UUID):
    with uow:
        value = uow.availability_exceptions.get(exception_id, owner_id)
        if value is None:
            raise LookupError("availability exception not found")
        return value


def _validate(uow: UnitOfWork, owner_id: str, value: AvailabilityException) -> None:
    today = datetime.now(ZoneInfo(value.timezone_name)).date()
    day = value.original_local_date
    if day is not None:
        if day < today:
            raise ValueError("past occurrences cannot be modified")
        rule = uow.recurring_availability.get(value.rule_id, owner_id)
        if rule is None:
            raise ValueError("target series does not exist for this owner")
        occurrences, expansion_issues = expand_rules((rule,), day, day + timedelta(days=1))
        if not occurrences or expansion_issues:
            raise ValueError("target occurrence does not exist or has invalid civil time")
        original_scope = occurrences[0].scope_id
        if value.scope_id not in (None, original_scope):
            raise ValueError("exception scope differs from its original occurrence")
        if original_scope is not None and value.scope_id is None:
            raise ValueError("scoped occurrence requires explicit scope provenance")
    if value.starts_at is not None and value.starts_at.astimezone(
            ZoneInfo(value.timezone_name)).date() < today:
        raise ValueError("exception must start today or later")
    if value.work_type_id and uow.work_types.get(value.work_type_id) is None:
        raise ValueError("work type does not exist")
    if value.scope_id is not None:
        scope = uow.schedule_scopes.get(owner_id, value.scope_id)
        if scope is None or scope.is_compatibility or scope.state != "ACTIVE":
            raise ValueError("scope does not exist or is not active for this owner")
        if value.work_type_id is not None:
            when = value.original_local_date or value.starts_at.astimezone(
                ZoneInfo(value.timezone_name)).date()
            if effective_scope(value.work_type_id, when,
                               uow.schedule_scopes.affiliations(owner_id),
                               compatibility_scope_id(owner_id)) != value.scope_id:
                raise ValueError("exception WorkType must belong to its scope")


def _window(value: AvailabilityException) -> tuple[date, date]:
    zone = ZoneInfo(value.timezone_name)
    if value.action is ExceptionAction.CANCEL:
        start = value.original_local_date
        assert start is not None
        return start, start + timedelta(days=1)
    assert value.starts_at is not None and value.ends_at is not None
    first = value.starts_at.astimezone(zone).date()
    last = value.ends_at.astimezone(zone).date() + timedelta(days=1)
    if value.original_local_date is not None:
        first = min(first, value.original_local_date)
        last = max(last, value.original_local_date + timedelta(days=1))
    if (last - first).days > 93:
        raise ValueError("preview window cannot exceed 93 days")
    return first, last


def _snapshot(rule_state, exception_state, manual, confirmed, proposed, old_id,
              scopes=(), affiliations=()):
    payload = {
        "algorithm": "TP-022B/v1",
        "rules": [asdict(item) for item in rule_state],
        "exceptions": [asdict(item) for item in exception_state],
        "manual": [asdict(item) for item in manual],
        "confirmed": [asdict(item) for item in confirmed],
        "proposed": asdict(proposed), "old_id": str(old_id),
        "scopes": [asdict(v) for v in scopes],
        "affiliations": [asdict(v) for v in affiliations],
    }
    return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _preview_loaded(uow: UnitOfWork, owner_id: str, proposed: AvailabilityException,
                    old_id: UUID | None):
    _validate(uow, owner_id, proposed)
    start, end = _window(proposed)
    rules, exceptions, manual, confirmed = _state(uow, owner_id, start, end)
    previous = next((e for e in exceptions if e.id == old_id), None)
    if old_id is not None and previous is None:
        raise LookupError("availability exception not found")
    if proposed.rule_id is not None and any(
        e.id != old_id and e.rule_id == proposed.rule_id
        and e.original_local_date == proposed.original_local_date for e in exceptions
    ):
        raise RuleConflict("another exception already targets this occurrence")
    if previous is not None and previous.version + 1 != proposed.version:
        raise RuleConflict("availability exception changed; reload and preview again")
    # For newly proposed records, the preview uses the deterministic sentinel
    # UUID 0. The id is not part of the snapshot hash nor capacity decision.
    selection = tuple(e for e in exceptions if e.id != old_id) + (proposed,)
    scopes = uow.schedule_scopes.list_owner(owner_id)
    affiliations = uow.schedule_scopes.affiliations(owner_id)
    projection = project_effective(rules, selection, manual, confirmed,
                                   start, end, proposed.timezone_name,
                                   compatibility_id=compatibility_scope_id(owner_id),
                                   affiliations=affiliations)
    fingerprint = _snapshot(rules, exceptions, manual, confirmed, proposed, old_id,
                            scopes, affiliations)
    return fingerprint, projection, (start, end)


def preview_exception(
    uow: UnitOfWork, owner_id: str, fields: dict, *,
    exception_id: UUID | None = None, expected_version: int | None = None,
):
    value = AvailabilityException(
        id=exception_id or UUID(int=0), owner_id=owner_id,
        version=(expected_version + 1 if expected_version is not None else 1), **fields,
    )
    if exception_id is not None and expected_version is None:
        raise ValueError("expected_version required when updating an exception")
    with uow:
        return _preview_loaded(uow, owner_id, value, exception_id)


def _audit(value: AvailabilityException, event_type: str) -> HistoryEvent:
    now = datetime.now(timezone.utc)
    payload = {key: str(item) if isinstance(item, (UUID, date, datetime))
               else item.value if hasattr(item, "value") else item
               for key, item in asdict(value).items()}
    return HistoryEvent(
        id=uuid4(), occurred_at=now, recorded_at=now,
        entity_type="AVAILABILITY_EXCEPTION", entity_id=value.id, task_id=None,
        event_type=event_type, schema_version=1, source=HistorySource.USER,
        reason_code=None, correlation_id=uuid4(), causation_id=None, payload=payload,
    )


def save_exception(
    uow: UnitOfWork, owner_id: str, fields: dict, fingerprint: str,
    acknowledge_conflicts: bool, *, exception_id: UUID | None = None,
    expected_version: int | None = None,
) -> AvailabilityException:
    if exception_id is not None and expected_version is None:
        raise ValueError("expected_version required when updating")
    candidate = AvailabilityException(
        id=exception_id or UUID(int=0), owner_id=owner_id,
        version=(expected_version + 1 if expected_version is not None else 1), **fields,
    )
    with uow:
        uow.lock_planning()
        actual, projection, _ = _preview_loaded(uow, owner_id, candidate, exception_id)
        if actual != fingerprint:
            raise RuleConflict("availability preview is stale; preview again")
        if (any(v.booking_id is not None for v in projection.issues)
                and not acknowledge_conflicts):
            raise ValueError("acknowledge booking conflicts before confirming the exception")
        saved = replace(candidate, id=exception_id or uuid4())
        if exception_id is None:
            uow.availability_exceptions.add(saved)
        else:
            uow.availability_exceptions.save(saved, expected_version=expected_version)
        uow.history.append(_audit(saved, "AVAILABILITY_EXCEPTION_DISABLED"
                                  if not saved.enabled else "AVAILABILITY_EXCEPTION_APPLIED"))
        uow.commit()
    return saved
