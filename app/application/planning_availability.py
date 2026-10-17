"""TP-022C: the single effective-availability input shared by planning consumers.

Declared capacity is not free time. Only a calendar-checked caller can present
verified free minutes; legacy manual blocks remain strict, never preferred.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.effective_availability import _state
from app.application.uow import UnitOfWork
from app.domain.capacity import AvailabilityBlock, validate_week_start
from app.domain.effective_availability import EffectiveProjection, project_effective
from app.domain.eligibility_projection import (EligibilityProjection, project_eligibility,
                                               reconcile_booking_issues)
from app.domain.recurring_availability import AvailabilityMode
from app.domain.schedule_scopes import compatibility_scope_id


@dataclass(frozen=True, slots=True)
class PlanningAvailability:
    projection: EffectiveProjection
    eligibility: EligibilityProjection
    blocks: tuple[AvailabilityBlock, ...]
    preferred_blocks: tuple[AvailabilityBlock, ...]
    revision_fingerprint: str


def effective_week(
    uow: UnitOfWork, owner_id: str, week_start: date, timezone_name: str,
) -> PlanningAvailability:
    """Caller owns the UoW transaction. Dates are half-open in the requested zone."""
    validate_week_start(week_start)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    until = week_start + timedelta(days=7)
    rules, exceptions, manual, confirmed = _state(uow, owner_id, week_start, until)
    projection = project_effective(
        rules, exceptions, manual, confirmed, week_start, until, timezone_name,
        compatibility_id=compatibility_scope_id(owner_id),
        affiliations=uow.schedule_scopes.affiliations(owner_id),
    )
    blocks = tuple(
        AvailabilityBlock(
            week_start=week_start,
            starts_at=item.starts_at.astimezone(zone),
            ends_at=item.ends_at.astimezone(zone),
            work_type_id=item.work_type_id, scope_id=item.scope_id,
            id=uuid5(NAMESPACE_URL, "taskplanner:effective:" + item.id),
        )
        for item in projection.blocks
    )
    series = tuple(uow.eligibility.list_owner(owner_id))
    permission_exceptions = tuple(uow.eligibility.list_exceptions(owner_id))
    eligibility = project_eligibility(
        projection, series, permission_exceptions, week_start, until,
        timezone_name, compatibility_id=compatibility_scope_id(owner_id),
        affiliations=uow.schedule_scopes.affiliations(owner_id),
    )
    projection, eligibility = reconcile_booking_issues(
        projection, eligibility, confirmed, compatibility_scope_id(owner_id))
    preferred_ids = {
        uuid5(NAMESPACE_URL, "taskplanner:effective:" + item.id)
        for item in projection.blocks if item.mode is AvailabilityMode.PREFERRED
    }
    snapshot = {
        "algorithm": "TP-025B/physical-eligibility-v1",
        "eligibility_series": [asdict(v) for v in series],
        "eligibility_exceptions": [asdict(v) for v in permission_exceptions],
        "eligibility_fragments": [asdict(v) for v in eligibility.fragments],
        "eligibility_issues": [asdict(v) for v in eligibility.issues],
        "scope_versions": uow.schedule_scopes.versions(owner_id),
        "affiliations": [asdict(v) for v in uow.schedule_scopes.affiliations(owner_id)],
        "scopes": [asdict(v) for v in uow.schedule_scopes.list_owner(owner_id)],
        "week": week_start.isoformat(), "timezone": timezone_name,
        "rules": [asdict(v) for v in rules],
        "exceptions": [asdict(v) for v in exceptions],
        "manual": [asdict(v) for v in manual],
        "confirmed": [asdict(v) for v in confirmed],
        "blocks": [asdict(v) for v in projection.blocks],
        "issues": [asdict(v) for v in projection.issues],
        "expansion_issues": [asdict(v) for v in projection.expansion_issues],
    }
    fingerprint = sha256(json.dumps(
        snapshot, default=str, sort_keys=True, ensure_ascii=True,
    ).encode()).hexdigest()
    return PlanningAvailability(
        projection, eligibility, blocks,
        tuple(v for v in blocks if v.id in preferred_ids), fingerprint,
    )
