"""Deterministic, read-only alternatives to a selected weekly workload."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Sequence
from uuid import UUID

from app.domain.capacity import (
    AvailabilityBlock, CapacityStatus, WeeklyCapacityEvaluation, evaluate_week,
)
from app.domain.model import (
    PlanningOption, PlanningProposal, ProtectionLevel, SegmentStatus,
)
from app.domain.task_rules import TaskAggregate


class PlanOptionKind(StrEnum):
    KEEP = "KEEP"
    DEFER = "DEFER"
    REVIEW_SCOPE = "REVIEW_SCOPE"
    CONSIDER_DELEGATION = "CONSIDER_DELEGATION"
    CLARIFY_ESTIMATES = "CLARIFY_ESTIMATES"


@dataclass(frozen=True, slots=True)
class PlanOptionPreview:
    option: PlanningOption
    kind: PlanOptionKind
    excluded_task_ids: tuple[UUID, ...]
    capacity: WeeklyCapacityEvaluation | None
    requires_confirmation: bool


@dataclass(frozen=True, slots=True)
class PlanProposalPreview:
    proposal: PlanningProposal
    week_start: date
    candidate_task_ids: tuple[UUID, ...]
    baseline: WeeklyCapacityEvaluation
    options: tuple[PlanOptionPreview, ...]


def effective_task_protection(aggregate: TaskAggregate) -> ProtectionLevel:
    """Whole-task deferral cannot hide any protected open segment."""
    active = (
        segment for segment in aggregate.segments
        if segment.status in {SegmentStatus.TODO, SegmentStatus.IN_PROGRESS}
    )
    levels = [aggregate.task.protection]
    levels.extend(aggregate.effective_segment_protection(s.id) for s in active)
    if ProtectionLevel.PROTECTED in levels:
        return ProtectionLevel.PROTECTED
    if ProtectionLevel.REPLANNABLE in levels:
        return ProtectionLevel.REPLANNABLE
    return ProtectionLevel.FLEXIBLE


def propose_plan(
    week_start: date,
    blocks: Sequence[AvailabilityBlock],
    candidates: Sequence[TaskAggregate],
) -> PlanProposalPreview:
    """Offer scenarios without accepting a decision or modifying a schedule.

    DEFER excludes exactly one eligible *whole task* from a hypothetical
    week. Qualitative options never invent a capacity improvement.
    """
    baseline = evaluate_week(week_start, blocks, candidates)
    ordered = sorted(candidates, key=lambda a: (a.task.title.casefold(), str(a.task.id)))
    task_ids = tuple(a.task.id for a in ordered)
    previews: list[PlanOptionPreview] = []

    def add(kind: PlanOptionKind, label: str, rationale: str,
            affected: tuple[UUID, ...], consequences: tuple[str, ...],
            capacity: WeeklyCapacityEvaluation | None,
            excluded: tuple[UUID, ...] = (),
            requires_confirmation: bool = True) -> None:
        previews.append(PlanOptionPreview(
            option=PlanningOption(
                label=label, rationale=rationale,
                affected_item_ids=affected, consequences=consequences,
            ),
            kind=kind,
            excluded_task_ids=excluded,
            capacity=capacity,
            requires_confirmation=requires_confirmation,
        ))

    add(
        PlanOptionKind.KEEP, "Conserver la sélection",
        "Ne rien déplacer et examiner la faisabilité actuelle.", task_ids,
        (
            f"Verdict actuel : {baseline.status.value}.",
            "Aucune réservation de calendrier ni décision n'est créée.",
        ), baseline, requires_confirmation=False,
    )

    for aggregate in ordered:
        protection = effective_task_protection(aggregate)
        if protection is ProtectionLevel.PROTECTED:
            continue
        remaining = [a for a in ordered if a.task.id != aggregate.task.id]
        simulated = evaluate_week(week_start, blocks, remaining)
        consequences = [
            "La tâche entière sort uniquement de la sélection hypothétique de cette semaine.",
            f"Capacité simulée : {simulated.status.value}; charge connue : "
            f"{simulated.known_demand_minutes} min, "
            f"{simulated.unestimated_units} unité(s) non estimée(s).",
            "Aucune date de reprise n'est déterminée et aucun engagement n'est déplacé.",
        ]
        if aggregate.task.due_at is not None:
            consequences.append(
                "Échéance existante inchangée : un report peut la compromettre."
            )
        if aggregate.effective_estimate().incomplete:
            consequences.append(
                "Estimation incomplète : le gain de charge total reste inconnu."
            )
        add(
            PlanOptionKind.DEFER, f"Reporter : {aggregate.task.title}",
            ("Travail flexible : report envisageable sous réserve de confirmation."
             if protection is ProtectionLevel.FLEXIBLE else
             "Travail important replanifiable : arbitrage explicite nécessaire."),
            (aggregate.task.id,), tuple(consequences), simulated,
            excluded=(aggregate.task.id,),
        )

    if baseline.status is CapacityStatus.OVER_CAPACITY:
        add(
            PlanOptionKind.REVIEW_SCOPE, "Réduire la portée à examiner",
            "Identifier manuellement les unités à retirer ou réduire sans inventer d'effort économisé.",
            task_ids,
            ("Aucun gain n'est présumé avant nouvelle estimation et sélection explicite.",
             "Les engagements protégés restent protégés."),
            capacity=None,
        )
        add(
            PlanOptionKind.CONSIDER_DELEGATION, "Explorer une délégation",
            "Vérifier avec l'utilisateur si une délégation est réaliste avant de modifier la charge.",
            task_ids,
            ("Aucune ressource, acceptation ni capacité externe n'est présumée.",
             "La faisabilité reste celle du scénario initial tant qu'aucune décision n'est prise."),
            capacity=None,
        )
    if baseline.unestimated_units:
        add(
            PlanOptionKind.CLARIFY_ESTIMATES, "Clarifier les estimations",
            "Compléter les estimations manquantes avant de conclure à la faisabilité.",
            task_ids,
            ("La charge inconnue n'est jamais convertie en zéro.",
             "Aucun travail n'est retiré de la sélection."),
            capacity=None, requires_confirmation=False,
        )

    proposal = PlanningProposal(
        options=tuple(preview.option for preview in previews),
        facts=(
            f"Semaine du {week_start.isoformat()} : sélection hypothétique de {len(ordered)} tâche(s).",
            f"Capacité de base : {baseline.status.value}, "
            f"{baseline.known_demand_minutes}/{baseline.available_minutes} min connus; "
            f"{baseline.unestimated_units} unité(s) non estimée(s).",
            "Les choix présentés ne sont ni acceptés ni appliqués.",
        ),
    )
    return PlanProposalPreview(
        proposal=proposal, week_start=week_start,
        candidate_task_ids=task_ids, baseline=baseline,
        options=tuple(previews),
    )
