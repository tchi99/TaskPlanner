"""Read-only deterministic assessment of hypothetical work displacement.

This module never considers the supplied original instant a committed schedule;
both instants are provided by the caller as a scenario, not looked up in a calendar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.domain.model import ProtectionLevel, SegmentStatus, TaskStatus
from app.domain.task_rules import TaskAggregate


@dataclass(frozen=True, slots=True)
class DisplacementAssessment:
    task_id: UUID
    segment_id: UUID | None
    protection: ProtectionLevel
    original_at: datetime
    proposed_at: datetime
    delay_minutes: int
    reason_code: str
    rationale: str
    consequences: tuple[str, ...]
    deadline_crossed: bool
    starts_after_deadline: bool
    confirmation_required: bool
    estimate_unknown: bool


def assess_displacement(
    aggregate: TaskAggregate,
    original_at: datetime,
    proposed_at: datetime,
    segment_id: UUID | None = None,
) -> DisplacementAssessment:
    for name, instant in (("original_at", original_at), ("proposed_at", proposed_at)):
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        if instant.second or instant.microsecond:
            raise ValueError(f"{name} must align to a whole minute")
    if aggregate.task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
        raise ValueError("only open clarified tasks can be assessed")

    if segment_id is not None:
        segment = next((s for s in aggregate.segments if s.id == segment_id), None)
        if segment is None:
            raise ValueError("segment does not belong to the task")
        if segment.status not in (SegmentStatus.TODO, SegmentStatus.IN_PROGRESS):
            raise ValueError("only open segments can be assessed")
        protection = aggregate.effective_segment_protection(segment_id)
        estimate_unknown = segment.estimated_minutes is None
    else:
        # A task-wide move cannot disguise a protected open child.
        active = [
            s for s in aggregate.segments
            if s.status in (SegmentStatus.TODO, SegmentStatus.IN_PROGRESS)
        ]
        protection = aggregate.task.protection
        if active and any(
            aggregate.effective_segment_protection(s.id) is ProtectionLevel.PROTECTED
            for s in active
        ):
            protection = ProtectionLevel.PROTECTED
        elif active and any(
            aggregate.effective_segment_protection(s.id) is ProtectionLevel.REPLANNABLE
            for s in active
        ):
            if protection is ProtectionLevel.FLEXIBLE:
                protection = ProtectionLevel.REPLANNABLE
        estimate_unknown = aggregate.effective_estimate().incomplete if (
            not aggregate.segments or active
        ) else False

    start = original_at.astimezone(timezone.utc)
    proposed = proposed_at.astimezone(timezone.utc)
    delay = max(0, int((proposed - start).total_seconds() // 60))
    moved = proposed != start
    deadline = aggregate.task.due_at
    due = deadline.astimezone(timezone.utc) if deadline else None
    crossed = due is not None and start < due <= proposed
    after = due is not None and proposed >= due
    consequences: list[str] = []
    if delay:
        consequences.append(f"Début proposé retardé de {delay} minute(s).")
    elif proposed < start:
        consequences.append("Début proposé avancé; vérifier les autres engagements.")
    if crossed:
        consequences.append("Le nouveau début atteint ou dépasse l'échéance de la tâche.")
    elif after:
        consequences.append("Le début proposé est déjà à l'échéance ou après celle-ci.")
    if estimate_unknown:
        consequences.append("Estimation incomplète : l'effet sur la charge reste incertain.")

    if not moved:
        reason = "NO_CHANGE"
        rationale = "Aucun changement d'horaire dans le scénario."
    elif delay and protection is ProtectionLevel.PROTECTED:
        reason = "PROTECTED_COMMITMENT"
        rationale = "Travail protégé : le report exige un arbitrage explicite."
    elif delay and protection is ProtectionLevel.REPLANNABLE:
        reason = "REPLANNABLE_TRADEOFF"
        rationale = "Travail important replanifiable : présenter et accepter le compromis."
    elif delay:
        reason = "FLEXIBLE_SLIP"
        rationale = "Travail flexible : report envisageable avec ses conséquences visibles."
    else:
        reason = "EARLIER_MOVE"
        rationale = "Avancement envisagé : vérifier les contraintes avant toute application."

    return DisplacementAssessment(
        task_id=aggregate.task.id,
        segment_id=segment_id,
        protection=protection,
        original_at=original_at,
        proposed_at=proposed_at,
        delay_minutes=delay,
        reason_code=reason,
        rationale=rationale,
        consequences=tuple(consequences),
        deadline_crossed=crossed,
        starts_after_deadline=after,
        confirmation_required=moved,
        estimate_unknown=estimate_unknown,
    )
