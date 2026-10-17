"""TP-025B: preview, revalidate and explicitly confirm local-only reservations.

Google is always read, never written. Physical eligibility and local bookings
are re-read under the same planning lock before a new confirmation is committed.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from typing import Sequence
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.calendar import CalendarReader
from app.application.history import HistoryEvent, HistorySource
from app.application.planning_availability import effective_week
from app.application.uow import UnitOfWork
from app.domain.capacity import validate_week_start
from app.domain.eligibility_allocator import FixedTimeRequest, suggest_eligible_blocks
from app.domain.schedule_scopes import compatibility_scope_id, effective_scope
from app.domain.time_blocks import (
    ConfirmedTimeBlock, TimeBlockPreview, suggest_time_blocks,
)


class StaleTimeBlockProposal(Exception):
    """Underlying calendar, capacity, permissions or reservations changed."""


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


def _confirmation_payload_hash(
    week_start: date, zone: str, task_ids: Sequence[UUID],
    expected_fingerprint: str | None, offer_transfers: bool,
    accept_transfers: bool, fixed_slots: Sequence[FixedTimeRequest],
) -> str:
    request = {
        "week": week_start.isoformat(), "timezone": zone,
        "tasks": [str(value) for value in task_ids],
        "fingerprint": expected_fingerprint,
        "offer_transfers": offer_transfers,
        "accept_transfers": accept_transfers,
        "fixed": [(str(item.task_id), str(item.segment_id),
                   item.starts_at.isoformat(), item.ends_at.isoformat())
                  for item in fixed_slots],
    }
    return sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def preview_time_blocks(
    uow: UnitOfWork, reader: CalendarReader, week_start: date,
    timezone_name: str, task_ids: Sequence[UUID],
    *, expected_fingerprint: str | None = None, confirm: bool = False,
    owner_id: str = "urn:taskplanner:local", offer_transfers: bool = False,
    accept_transfers: bool = False, command_id: UUID | None = None,
    fixed_slots: Sequence[FixedTimeRequest] = (),
) -> tuple[TimeBlockPreview, tuple[ConfirmedTimeBlock, ...]]:
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("candidate tasks must be nonempty and unique")
    start, end = _window(week_start, timezone_name)
    payload_hash = _confirmation_payload_hash(
        week_start, timezone_name, task_ids, expected_fingerprint,
        offer_transfers, accept_transfers, fixed_slots)
    with uow:
        if confirm:
            # SQLite BEGIN IMMEDIATE / Postgres advisory transaction lock.
            # It precedes EVERY local planning read, including idempotency lookup.
            uow.lock_planning()
            if command_id is not None:
                previous = uow.time_block_commands.get(owner_id, command_id)
                if previous is not None:
                    if previous.payload_hash != payload_hash:
                        raise StaleTimeBlockProposal(
                            "command_id was used for another confirmation")
                    bookings = tuple(
                        uow.time_blocks.get(UUID(value))
                        for value in previous.result["booking_ids"])
                    if any(item is None for item in bookings):
                        raise StaleTimeBlockProposal("booking receipt cannot be replayed")
                    # A replay is a read of an already accepted command, not a new
                    # planning decision and not another calendar operation.
                    return (TimeBlockPreview(
                        week_start, timezone_name, tuple(task_ids),
                        expected_fingerprint or "", (), (), True), bookings)
        # Never synthesize empty Google results for missing/failed integration.
        commitments = tuple(reader.list_commitments(start, end, timezone_name))
        availability = effective_week(uow, owner_id, week_start, timezone_name)
        existing = tuple(uow.time_blocks.list_week(week_start))
        candidates = []
        for task_id in task_ids:
            aggregate = uow.tasks.get_aggregate(task_id)
            if aggregate is None:
                raise LookupError(f"task {task_id} not found")
            candidates.append(aggregate)
        affiliations = uow.schedule_scopes.affiliations(owner_id)
        compatibility = compatibility_scope_id(owner_id)
        type_scopes = {}
        for work_type in uow.work_types.list_all():
            first = effective_scope(work_type.id, week_start, affiliations, compatibility)
            if all(effective_scope(work_type.id, week_start + timedelta(days=i),
                                   affiliations, compatibility) == first
                   for i in range(1, 7)):
                type_scopes[work_type.id] = first
        shared = any(
            not choice.exclusive
            for fragment in availability.eligibility.fragments
            for choice in fragment.choices
        )
        if shared or fixed_slots:
            result = suggest_eligible_blocks(
                week_start, timezone_name, availability.eligibility,
                commitments, existing, candidates,
                availability_fingerprint=availability.revision_fingerprint,
                fixed=fixed_slots, offer_transfers=offer_transfers,
                work_type_scopes=type_scopes,
            )
        else:
            result = suggest_time_blocks(
                week_start, timezone_name, availability.blocks, commitments,
                existing, candidates, preferred_blocks=availability.preferred_blocks,
                offer_transfers=offer_transfers,
                availability_fingerprint=availability.revision_fingerprint,
                work_type_scopes=type_scopes,
            )
        if not confirm:
            return result, ()
        if (shared or fixed_slots) and command_id is None:
            raise ValueError("command_id is required for shared or fixed confirmations")
        if not expected_fingerprint or expected_fingerprint != result.fingerprint:
            raise StaleTimeBlockProposal("proposal is stale; request a new preview")
        if not result.can_confirm:
            raise ValueError("proposal is incomplete and cannot be confirmed")
        if result.requires_transfer_confirmation and not accept_transfers:
            raise ValueError("PREFERRED transfers require explicit acceptance")

        def source_scope(item):
            if item.scope_id is not None:
                # Allocation produced this provenance from one physical minute
                # per interval, which was revalidated under the planning lock.
                return item.scope_id
            donor = item.transferred_from or item.work_type_id
            matches = {
                block.scope_id for block in availability.blocks
                if block.work_type_id == donor
                and block.starts_at <= item.starts_at.astimezone(block.starts_at.tzinfo)
                and block.ends_at >= item.ends_at.astimezone(block.ends_at.tzinfo)
            }
            if len(matches) != 1:
                raise ValueError("booking scope is ambiguous or unavailable; preview again")
            return next(iter(matches))

        if any(source_scope(item) == compatibility for item in result.suggestions):
            uow.schedule_scopes.ensure_compatibility(owner_id)
        accepted = tuple(ConfirmedTimeBlock(
            week_start=week_start, task_id=s.task_id, segment_id=s.segment_id,
            work_type_id=s.work_type_id, starts_at=s.starts_at, ends_at=s.ends_at,
            transferred_from=s.transferred_from, scope_id=source_scope(s),
        ) for s in result.suggestions)
        now = datetime.now(timezone.utc)
        correlation = command_id or uuid4()
        for suggestion, block in zip(result.suggestions, accepted):
            uow.time_blocks.add(block)
            uow.history.append(HistoryEvent(
                id=uuid4(), occurred_at=now, recorded_at=now,
                entity_type="TIME_BLOCK", entity_id=block.id,
                task_id=block.task_id, event_type="TIME_BLOCK_CONFIRMED",
                schema_version=1, source=HistorySource.USER,
                reason_code=suggestion.placement_reason,
                correlation_id=correlation, causation_id=None,
                payload={
                    "work_type_id": str(block.work_type_id) if block.work_type_id else None,
                    "scope_id": str(block.scope_id) if block.scope_id else None,
                    "segment_id": str(block.segment_id) if block.segment_id else None,
                    "starts_at": block.starts_at.isoformat(),
                    "ends_at": block.ends_at.isoformat(),
                    "minutes": suggestion.minutes,
                    "eligibility_sources": list(suggestion.eligibility_sources),
                    "priority_rank": suggestion.priority_rank,
                    "transferred_from": (str(block.transferred_from)
                                         if block.transferred_from else None),
                    "preview_fingerprint": expected_fingerprint,
                    "command_id": str(command_id) if command_id else None,
                },
            ))
        if command_id is not None:
            uow.time_block_commands.add(owner_id, command_id, payload_hash, {
                "booking_ids": [str(item.id) for item in accepted],
                "fingerprint": result.fingerprint,
            })
        uow.commit()
        return result, accepted


def list_confirmed_time_blocks(
    uow: UnitOfWork, week_start: date
) -> tuple[ConfirmedTimeBlock, ...]:
    validate_week_start(week_start)
    with uow:
        return tuple(uow.time_blocks.list_week(week_start))
