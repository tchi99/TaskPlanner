"""Read-only proposal use case; no new persistence or calendar adapter."""
from __future__ import annotations

from datetime import date
from typing import Sequence
from uuid import UUID

from app.application.uow import UnitOfWork
from app.application.planning_availability import effective_week
from app.domain.capacity import validate_week_start
from app.domain.eligibility_capacity import evaluate_eligibility_week
from app.domain.planning import PlanProposalPreview, propose_plan


def propose_week(uow: UnitOfWork, week_start: date,
                 task_ids: Sequence[UUID], timezone_name: str = "UTC",
                 owner_id: str = "urn:taskplanner:local") -> PlanProposalPreview:
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
        evaluator = lambda tasks: evaluate_eligibility_week(
            week_start, timezone_name, blocks, availability.eligibility, tasks,
        )
        return propose_plan(week_start, blocks, aggregates,
                            preferred_declared_minutes=0,
                            capacity_evaluator=evaluator)
