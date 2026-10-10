"""Read-only, ephemeral AI decomposition proposals (TP-050)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.application.uow import UnitOfWork
from app.domain import TaskStatus


class SuggestedWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    duration_min_minutes: int | None = Field(default=None, gt=0, le=10080)
    duration_max_minutes: int | None = Field(default=None, gt=0, le=10080)
    # One-based indices referring only to earlier items in the same list.
    depends_on: list[int] = Field(default_factory=list, max_length=6)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("suggestion title must not be blank")
        return value

    @model_validator(mode="after")
    def consistent_duration(self) -> "SuggestedWorkItem":
        minimum, maximum = self.duration_min_minutes, self.duration_max_minutes
        if (minimum is None) != (maximum is None):
            raise ValueError("duration range must be complete or unknown")
        if minimum is not None and maximum is not None and maximum < minimum:
            raise ValueError("duration maximum must be at least the minimum")
        return self


class DecompositionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[SuggestedWorkItem] = Field(default_factory=list, max_length=6)
    subtasks: list[SuggestedWorkItem] = Field(default_factory=list, max_length=6)
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("clarification_questions")
    @classmethod
    def questions_are_short(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 300 for value in cleaned):
            raise ValueError("clarification questions must be nonblank and short")
        return cleaned

    @model_validator(mode="after")
    def validate_dependencies(self) -> "DecompositionDraft":
        if not (self.segments or self.subtasks or self.clarification_questions):
            raise ValueError("an empty decomposition is not a useful proposal")
        for items in (self.segments, self.subtasks):
            seen: set[str] = set()
            for position, item in enumerate(items, start=1):
                key = item.title.casefold()
                if key in seen:
                    raise ValueError("duplicate suggested work item")
                seen.add(key)
                if (len(set(item.depends_on)) != len(item.depends_on)
                        or any(dep < 1 or dep >= position for dep in item.depends_on)):
                    raise ValueError("dependencies must reference distinct earlier items")
        return self


class DecompositionResponse(DecompositionDraft):
    task_id: UUID
    state: str = "PROPOSED"
    source: str = "AI_SUGGESTION"


@dataclass(frozen=True, slots=True)
class DecompositionContext:
    task_id: UUID
    title: str
    notes: str | None
    estimated_minutes: int | None
    existing_segments: tuple[str, ...]


class DecompositionAssistant(Protocol):
    def suggest(self, context: DecompositionContext) -> DecompositionDraft: ...


def suggest_decomposition(
    uow: UnitOfWork, task_id: UUID, assistant: DecompositionAssistant
) -> DecompositionResponse:
    # Load a snapshot, never save it. No mutation, no history, no calendar.
    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        if aggregate.task.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            raise ValueError("only open clarified tasks can be decomposed")
        context = DecompositionContext(
            task_id=aggregate.task.id,
            title=aggregate.task.title,
            notes=aggregate.task.notes,
            estimated_minutes=aggregate.task.estimated_minutes,
            existing_segments=tuple(
                segment.title for segment in sorted(
                    aggregate.segments, key=lambda s: s.position
                ) if segment.status.value in {"TODO", "IN_PROGRESS"}
            ),
        )
    draft = assistant.suggest(context)
    # Validate even injected adapters before returning to the caller.
    validated = DecompositionDraft.model_validate(draft)
    return DecompositionResponse(task_id=task_id, **validated.model_dump())
