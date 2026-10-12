"""TP-022A use cases: series edits are future-only, explicit and revisioned."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.application.history import HistoryEvent, HistorySource
from app.application.uow import UnitOfWork
from app.domain.recurring_availability import (
    RecurringAvailabilityRule, RuleConflict, RuleRevision, expand_rules,
)


def _ensure_future(revision: RuleRevision) -> None:
    today = datetime.now(ZoneInfo(revision.timezone_name)).date()
    if revision.effective_from < today:
        raise ValueError("rule changes must start today or later in the rule timezone")


def _audit(rule_id: UUID, number: int, effective_from: date, action: str) -> HistoryEvent:
    at = datetime.now(timezone.utc)
    return HistoryEvent(
        id=uuid4(), occurred_at=at, recorded_at=at,
        entity_type="AVAILABILITY_RULE", entity_id=rule_id, task_id=None,
        event_type=action, schema_version=1, source=HistorySource.USER,
        reason_code=None, correlation_id=uuid4(), causation_id=None,
        payload={"version": number, "effective_from": effective_from.isoformat()},
    )


def _check_work_type(uow: UnitOfWork, revision: RuleRevision) -> None:
    if revision.work_type_id is not None and uow.work_types.get(revision.work_type_id) is None:
        raise ValueError("work type does not exist")


def create_rule(
    uow: UnitOfWork, owner_id: str, fields: dict,
) -> RecurringAvailabilityRule:
    if not owner_id or len(owner_id) > 128:
        raise ValueError("invalid rule owner")
    identity = uuid4()
    revision = RuleRevision(rule_id=identity, number=1, **fields)
    _ensure_future(revision)
    rule = RecurringAvailabilityRule(identity, owner_id, 1, (revision,))
    with uow:
        _check_work_type(uow, revision)
        uow.recurring_availability.add(rule)
        uow.history.append(_audit(rule.id, 1, revision.effective_from, "AVAILABILITY_RULE_CREATED"))
        uow.commit()
    return rule


def get_rule(uow: UnitOfWork, owner_id: str, rule_id: UUID) -> RecurringAvailabilityRule:
    with uow:
        rule = uow.recurring_availability.get(rule_id, owner_id)
        if rule is None:
            raise LookupError("recurring rule not found")
        return rule


def list_rules(uow: UnitOfWork, owner_id: str) -> tuple[RecurringAvailabilityRule, ...]:
    with uow:
        return tuple(uow.recurring_availability.list_owner(owner_id))


def revise_rule(
    uow: UnitOfWork, owner_id: str, rule_id: UUID, expected_version: int,
    fields: dict | None, *, disable_from: date | None = None,
) -> RecurringAvailabilityRule:
    if expected_version < 1:
        raise ValueError("expected_version must be positive")
    with uow:
        current = uow.recurring_availability.get(rule_id, owner_id)
        if current is None:
            raise LookupError("recurring rule not found")
        if current.version != expected_version:
            raise RuleConflict("recurring rule changed; reload before updating")
        if disable_from is not None:
            revision = replace(
                current.revisions[-1], number=expected_version + 1,
                effective_from=disable_from, valid_until=None, enabled=False,
            )
        else:
            if fields is None:
                raise ValueError("revision settings required")
            revision = RuleRevision(rule_id=rule_id, number=expected_version + 1, **fields)
        _ensure_future(revision)
        if revision.effective_from <= current.revisions[-1].effective_from:
            raise ValueError("new revision must start after the previous effective date")
        _check_work_type(uow, revision)
        proposed = RecurringAvailabilityRule(
            current.id, current.owner_id, current.version + 1,
            (*current.revisions, revision),
        )
        # Do not silently orphan a future exception when changing the series.
        for exc in uow.availability_exceptions.list_owner(owner_id):
            if (exc.enabled and exc.rule_id == rule_id and
                    exc.original_local_date is not None and
                    exc.original_local_date >= revision.effective_from):
                values, problems = expand_rules(
                    (proposed,), exc.original_local_date,
                    exc.original_local_date + timedelta(days=1),
                )
                if not values or problems:
                    raise RuleConflict(
                        "series edit would orphan a future exception; resolve it explicitly"
                    )
        uow.recurring_availability.append_revision(revision, expected_version=expected_version)
        uow.history.append(_audit(rule_id, revision.number, revision.effective_from,
                                  "AVAILABILITY_RULE_DISABLED" if not revision.enabled
                                  else "AVAILABILITY_RULE_CHANGED"))
        uow.commit()
        return RecurringAvailabilityRule(
            current.id, current.owner_id, current.version + 1,
            (*current.revisions, revision),
        )


def read_occurrences(
    uow: UnitOfWork, owner_id: str, from_date: date, to_date: date,
):
    # Validate the window before querying any possibly large collection.
    days = (to_date - from_date).days
    if not 0 < days <= 93:
        raise ValueError("expansion requires 1 to 93 days")
    with uow:
        rules = tuple(uow.recurring_availability.list_owner(owner_id))
    return expand_rules(rules, from_date, to_date)
