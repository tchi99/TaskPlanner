"""TP-070: read-only starting advice and confirmed minimal resume notes."""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.application.uow import UnitOfWork
from app.domain.start import (
    ResumePoint, StarterAction, StartingStrategy, suggest_starter, starting_strategies,
)
from app.domain.task_rules import NextAction, NextActionType, TaskAggregate


class StaleResumePointError(Exception):
    """The user's read revision or next-action target is no longer current."""


@dataclass(frozen=True, slots=True)
class StartAssistance:
    next_action: NextAction | None
    starter_action: StarterAction | None
    strategies: tuple[StartingStrategy, ...]
    resume_point: ResumePoint | None
    resume_revision: int


def _projection(aggregate: TaskAggregate, marker: ResumePoint | None) -> StartAssistance:
    action = aggregate.next_action()
    return StartAssistance(
        next_action=action,
        starter_action=suggest_starter(action),
        strategies=starting_strategies(action),
        resume_point=marker if marker and marker.matches(action) else None,
        resume_revision=marker.revision if marker else 0,
    )


def get_start_assistance(uow: UnitOfWork, task_id: UUID) -> StartAssistance:
    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        return _projection(aggregate, uow.resume_points.get(task_id))


def save_resume_point(
    uow: UnitOfWork, task_id: UUID, *, text: str | None,
    action_type: NextActionType, target_id: UUID, expected_revision: int,
    confirmed: bool,
) -> StartAssistance:
    if not confirmed:
        raise ValueError("explicit confirmation is required")
    if text is not None:
        text = text.strip()
        if not text or len(text) > 240:
            raise ValueError("resume text must be between 1 and 240 characters")

    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        action = aggregate.next_action()
        if action is None:
            raise ValueError("a completed or cancelled task has no next action")
        if action.action_type != action_type or action.target_id != target_id:
            raise StaleResumePointError("next action changed; reload before saving")

        old = uow.resume_points.get(task_id)
        revision = old.revision if old else 0
        if revision != expected_revision:
            raise StaleResumePointError("resume point changed; reload before saving")
        if old and old.text == text and old.matches(action) == bool(text):
            return _projection(aggregate, old)

        updated = ResumePoint(
            task_id=task_id, action_type=action.action_type,
            target_id=action.target_id, text=text, revision=revision + 1,
            updated_at=datetime.now(timezone.utc),
        )
        uow.resume_points.save(updated)
        uow.commit()
        return _projection(aggregate, updated)
