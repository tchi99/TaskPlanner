"""TP-041: propose, revalidate, explicitly confirm local time reservations."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.calendar import CalendarReader
from app.application.planning_availability import effective_week
from app.application.uow import UnitOfWork
from app.domain.capacity import validate_week_start
from app.domain.time_blocks import (
    ConfirmedTimeBlock, TimeBlockPreview, suggest_time_blocks,
)


class StaleTimeBlockProposal(Exception):
    """Underlying calendar, capacity, work or reservations changed."""


def _window(week_start: date, timezone_name: str) -> tuple[datetime, datetime]:
    validate_week_start(week_start)
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    return (
        datetime.combine(week_start, time.min, tzinfo=zone),
        datetime.combine(week_start + timedelta(days=7), time.min, tzinfo=zone),
    )


def preview_time_blocks(
    uow: UnitOfWork, reader: CalendarReader, week_start: date,
    timezone_name: str, task_ids: Sequence[UUID],
    *, expected_fingerprint: str | None = None, confirm: bool = False,
    owner_id: str = "urn:taskplanner:local", offer_transfers: bool = False,
    accept_transfers: bool = False,
) -> tuple[TimeBlockPreview, tuple[ConfirmedTimeBlock, ...]]:
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("candidate tasks must be nonempty and unique")
    start, end = _window(week_start, timezone_name)
    # Always fail closed on missing/failed calendar reads (no empty-calendar fallback).
    commitments = tuple(reader.list_commitments(start, end, timezone_name))
    with uow:
        # The lock precedes all local reads/revalidation and is held through commit.
        # The external calendar has no locking guarantee (read-only API).
        if confirm:
            uow.lock_planning()
        availability = effective_week(uow, owner_id, week_start, timezone_name)
        blocks = availability.blocks
        existing = tuple(uow.time_blocks.list_week(week_start))
        candidates = []
        for task_id in task_ids:
            aggregate = uow.tasks.get_aggregate(task_id)
            if aggregate is None:
                raise LookupError(f"task {task_id} not found")
            candidates.append(aggregate)
        result = suggest_time_blocks(
            week_start, timezone_name, blocks, commitments, existing, candidates,
            preferred_blocks=availability.preferred_blocks,
            offer_transfers=offer_transfers,
            availability_fingerprint=availability.revision_fingerprint,
        )
        if not confirm:
            return result, ()
        if not expected_fingerprint or expected_fingerprint != result.fingerprint:
            raise StaleTimeBlockProposal("proposal is stale; request a new preview")
        if not result.can_confirm:
            raise ValueError("proposal is incomplete and cannot be confirmed")
        if result.requires_transfer_confirmation and not accept_transfers:
            raise ValueError("PREFERRED transfers require explicit acceptance")
        accepted = tuple(ConfirmedTimeBlock(
            week_start=week_start,
            task_id=s.task_id,
            segment_id=s.segment_id,
            work_type_id=s.work_type_id,
            starts_at=s.starts_at,
            ends_at=s.ends_at,
            transferred_from=s.transferred_from,
        ) for s in result.suggestions)
        for block in accepted:
            uow.time_blocks.add(block)
        uow.commit()
        return result, accepted


def list_confirmed_time_blocks(
    uow: UnitOfWork, week_start: date
) -> tuple[ConfirmedTimeBlock, ...]:
    validate_week_start(week_start)
    with uow:
        return tuple(uow.time_blocks.list_week(week_start))
