"""Read-only displacement preview; no persistence or calendar changes."""
from datetime import datetime
from uuid import UUID

from app.application.uow import UnitOfWork
from app.domain.protection import DisplacementAssessment, assess_displacement


def preview_displacement(
    uow: UnitOfWork,
    task_id: UUID,
    original_at: datetime,
    proposed_at: datetime,
    segment_id: UUID | None = None,
) -> DisplacementAssessment:
    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        return assess_displacement(aggregate, original_at, proposed_at, segment_id)
