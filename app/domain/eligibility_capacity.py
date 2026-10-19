"""Declared-only feasibility over a single non-additive physical timeline.

This is not a Google-verified free-time promise. Per-activity figures are
alternative potentials; they must never be summed into physical capacity.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Sequence
from uuid import UUID

from app.domain.capacity import (
    AvailabilityBlock, CapacityStatus, WeeklyCapacityEvaluation,
    WorkTypeCapacity, evaluate_week,
)
from app.domain.eligibility_allocator import suggest_eligible_blocks
from app.domain.eligibility_projection import EligibilityProjection
from app.domain.task_rules import TaskAggregate


def evaluate_eligibility_week(
    week_start: date, timezone_name: str,
    physical_blocks: Sequence[AvailabilityBlock],
    eligibility: EligibilityProjection,
    candidates: Sequence[TaskAggregate],
) -> WeeklyCapacityEvaluation:
    previous = evaluate_week(week_start, physical_blocks, candidates)
    possibilities: dict[tuple[UUID | None, UUID | None], int] = defaultdict(int)
    alternatives = set()
    for fragment in eligibility.fragments:
        scope = fragment.scope_id
        for choice in fragment.choices:
            key = (scope, choice.work_type_id)
            possibilities[key] += fragment.minutes
            if len(fragment.choices) > 1:
                alternatives.add(key)
        if fragment.null_residual:
            possibilities[(scope, None)] += fragment.minutes

    demand: dict[tuple[UUID | None, UUID | None], list[int]] = defaultdict(
        lambda: [0, 0])
    by_type_scopes: dict[UUID | None, set[UUID | None]] = defaultdict(set)
    for scope, work_type in possibilities:
        by_type_scopes[work_type].add(scope)
    for bucket in previous.by_work_type:
        # In a multi-parent week, an ambiguous date-varying affiliation is
        # never inferred from a display name or borrowed from another scope.
        scope = bucket.scope_id
        if scope is None and len(by_type_scopes[bucket.work_type_id]) == 1:
            scope = next(iter(by_type_scopes[bucket.work_type_id]))
        entry = demand[(scope, bucket.work_type_id)]
        entry[0] += bucket.known_demand_minutes
        entry[1] += bucket.unestimated_units

    rows = []
    for key in sorted(set(possibilities) | set(demand),
                      key=lambda value: (str(value[0]), str(value[1]))):
        capacity = possibilities.get(key, 0)
        known, unknown = demand.get(key, [0, 0])
        local_status = (
            CapacityStatus.INCOMPLETE if key[1] is None and (known or unknown)
            else CapacityStatus.OVER_CAPACITY if known > capacity
            else CapacityStatus.INCOMPLETE if unknown
            else CapacityStatus.FEASIBLE
        )
        rows.append(WorkTypeCapacity(
            work_type_id=key[1], scope_id=key[0],
            available_minutes=capacity, known_demand_minutes=known,
            unestimated_units=unknown, remaining_minutes=capacity - known,
            status=local_status, alternative_potential=key in alternatives,
        ))
    # Claimed feasibility also needs an actual (non-Google-verified) bounded
    # greedy placement, not just individually sufficient type potentials.
    no_placement = False
    if candidates and previous.unestimated_units == 0:
        proposal = suggest_eligible_blocks(
            week_start, timezone_name, eligibility, (), (), candidates,
            availability_fingerprint="DECLARED_ONLY",
        )
        no_placement = bool(proposal.unplaced)
    status = (
        CapacityStatus.OVER_CAPACITY
        if previous.known_demand_minutes > eligibility.physical_minutes
        or any(row.status is CapacityStatus.OVER_CAPACITY for row in rows)
        else CapacityStatus.INCOMPLETE if previous.unestimated_units
        or any(row.work_type_id is None and row.known_demand_minutes
               for row in rows)
        else CapacityStatus.PLACEMENT_NOT_FOUND if no_placement
        else CapacityStatus.FEASIBLE
    )
    return WeeklyCapacityEvaluation(
        week_start=week_start, available_minutes=eligibility.physical_minutes,
        known_demand_minutes=previous.known_demand_minutes,
        unestimated_units=previous.unestimated_units,
        remaining_minutes=eligibility.physical_minutes - previous.known_demand_minutes,
        status=status, by_work_type=tuple(rows),
    )
