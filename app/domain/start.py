"""Non-authoritative starting suggestions and explicitly saved resume markers."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.task_rules import NextAction, NextActionType


@dataclass(frozen=True, slots=True)
class StarterAction:
    text: str
    commitment_minutes: int


@dataclass(frozen=True, slots=True)
class StartingStrategy:
    code: str
    label: str


@dataclass(frozen=True, slots=True)
class ResumePoint:
    task_id: UUID
    action_type: NextActionType
    target_id: UUID
    text: str | None
    revision: int
    updated_at: datetime

    def matches(self, action: NextAction | None) -> bool:
        return bool(
            self.text and action
            and self.action_type == action.action_type
            and self.target_id == action.target_id
        )


def suggest_starter(action: NextAction | None) -> StarterAction | None:
    """A disposable suggestion. Never calculate or persist a second next action."""
    if action is None:
        return None
    if action.action_type is NextActionType.CLARIFY_TASK:
        return StarterAction(
            "Ouvrir «" + action.label + "» et écrire le résultat attendu en une phrase.",
            5,
        )
    if action.action_type is NextActionType.REVIEW_COMPLETION:
        return StarterAction(
            "Relire «" + action.label + "» et vérifier ce qui reste à clôturer.",
            5,
        )
    return StarterAction(
        "Ouvrir les éléments nécessaires à «" + action.label
        + "» et effectuer une première petite étape, sans viser la fin.",
        10,
    )


def starting_strategies(action: NextAction | None) -> tuple[StartingStrategy, ...]:
    if action is None:
        return ()
    return (
        StartingStrategy("SHORT_COMMITMENT", "Essayer seulement 5 à 15 minutes"),
        StartingStrategy("DECOMPOSE", "Découper l'action en un segment plus petit"),
        StartingStrategy("REDUCE_SCOPE", "Réduire temporairement l'étendue"),
        StartingStrategy("ALTERNATE", "Choisir une autre unité de travail appropriée"),
        StartingStrategy("BODY_DOUBLING", "Travailler avec une présence externe (body doubling)"),
    )
