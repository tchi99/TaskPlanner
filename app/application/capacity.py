"""Use cases for manual weekly capacity blocks and read-only evaluations."""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence
from uuid import UUID

from app.application.uow import UnitOfWork
from app.application.planning_availability import effective_week
from app.domain.eligibility_capacity import evaluate_eligibility_week
from app.domain.capacity import (
    AvailabilityBlock,
    WeeklyCapacityEvaluation,
    evaluate_week,
    validate_blocks,
    validate_week_start,
)


def list_blocks(uow: UnitOfWork, week_start: date) -> Sequence[AvailabilityBlock]:
    validate_week_start(week_start)
    with uow:
        return tuple(uow.availability.list_week(week_start))


def add_block(
    uow: UnitOfWork,
    week_start: date,
    starts_at: datetime,
    ends_at: datetime,
    work_type_id: UUID | None = None,
) -> AvailabilityBlock:
    raise ValueError("legacy manual capacity writes were removed; configure a parent envelope")
    block = AvailabilityBlock(
        week_start=week_start,
        starts_at=starts_at,
        ends_at=ends_at,
        work_type_id=work_type_id,
    )
    with uow:
        uow.lock_planning()
        if work_type_id is not None and uow.work_types.get(work_type_id) is None:
            raise ValueError("work type does not exist")
        validate_blocks(week_start, (*uow.availability.list_week(week_start), block))
        uow.availability.add(block)
        uow.commit()
    return block


def delete_block(uow: UnitOfWork, week_start: date, block_id: UUID) -> None:
    validate_week_start(week_start)
    with uow:
        uow.lock_planning()
        block = uow.availability.get(block_id)
        if block is None or block.week_start != week_start:
            raise LookupError("availability block not found")
        if any(
            existing.starts_at < block.ends_at and existing.ends_at > block.starts_at
            for existing in uow.time_blocks.list_week(week_start)
        ):
            raise ValueError("availability is used by confirmed time blocks")
        uow.availability.delete(block_id)
        uow.commit()


def evaluate_selection(
    uow: UnitOfWork, week_start: date, task_ids: Sequence[UUID],
    timezone_name: str = "UTC", owner_id: str = "urn:taskplanner:local",
) -> WeeklyCapacityEvaluation:
    validate_week_start(week_start)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("candidate tasks must be unique")
    with uow:
        availability = effective_week(uow, owner_id, week_start, timezone_name)
        blocks = availability.blocks
        aggregates = []
        for task_id in task_ids:
            aggregate = uow.tasks.get_aggregate(task_id)
            if aggregate is None:
                raise LookupError(f"task {task_id} not found")
            aggregates.append(aggregate)
        return evaluate_eligibility_week(
            week_start, timezone_name, blocks, availability.eligibility, aggregates,
        )
