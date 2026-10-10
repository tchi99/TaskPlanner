"""TP-051: optional explanation of deterministic, ephemeral planning options."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.application.planning import propose_week
from app.application.uow import UnitOfWork
from app.domain.planning import PlanProposalPreview


class ArbitrationNotConfigured(Exception):
    """An optional AI provider has not been configured."""


class ArbitrationUnavailable(Exception):
    """An AI explanation could not safely be returned."""


class OptionExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Position refers to a deterministic option in THIS response, not a durable ID.
    option_index: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=600)
    question: str | None = Field(default=None, max_length=300)

    @field_validator("explanation", "question")
    @classmethod
    def nonblank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("AI text cannot be blank")
        return value


class ArbitrationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanations: list[OptionExplanation] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def unique_positions(self) -> "ArbitrationDraft":
        positions = [item.option_index for item in self.explanations]
        if len(set(positions)) != len(positions):
            raise ValueError("duplicate option explanations")
        return self


class ArbitrationAssistant(Protocol):
    def explain(self, proposal: PlanProposalPreview) -> ArbitrationDraft: ...


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    proposal: PlanProposalPreview
    explanations: tuple[OptionExplanation, ...]


def explain_week(
    uow: UnitOfWork, week_start: date, task_ids: Sequence[UUID],
    assistant: ArbitrationAssistant,
) -> ArbitrationResult:
    # The deterministic proposal is always recomputed and remains authoritative.
    proposal = propose_week(uow, week_start, task_ids)
    if len(proposal.options) > 25:
        raise ValueError("AI assistance supports at most 25 options per request")
    try:
        raw = assistant.explain(proposal)
        draft = ArbitrationDraft.model_validate(raw)
    except (ValidationError, TypeError) as exc:
        raise ArbitrationUnavailable("Invalid AI explanation") from exc

    # Reject missing, fabricated and reordered options rather than silently
    # attaching a narrative to the wrong scenario.
    if [item.option_index for item in draft.explanations] != list(range(len(proposal.options))):
        raise ArbitrationUnavailable("AI explanation did not match the proposal")
    return ArbitrationResult(proposal=proposal, explanations=tuple(draft.explanations))
