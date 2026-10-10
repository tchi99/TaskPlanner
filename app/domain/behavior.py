"""TP-072: deterministic, descriptive projections and optional interventions.

These values are read models, not observed facts, decisions, diagnoses or inferred
causes. They never change Tasks, WorkSessions, history or calendar commitments.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import AbstractSet, Mapping, Sequence
from uuid import UUID

from app.application.history import HistoryEvent, HistorySource
from app.domain.model import Task, TaskStatus
from app.domain.work_sessions import SessionStatus, WorkSession

MIN_SAMPLES = 3
QUIET_DAYS = 14
OPEN = {TaskStatus.INBOX, TaskStatus.TODO, TaskStatus.IN_PROGRESS}
DECLARED_REASONS = {"BLOCKED", "MISSING_INFORMATION", "INTERRUPTION", "LOW_ENERGY"}


def project_behavior(
    *, as_of: datetime, tasks: Sequence[Task], events: Sequence[HistoryEvent],
    sessions: Sequence[WorkSession], decomposed_ids: AbstractSet[UUID],
    calibration: Sequence[Mapping[str, object]],
) -> dict:
    """Build read-only descriptions from the minimum available operational data.

    Population-wide trends require three *distinct tasks* for facts/sessions,
    or three completed units for TP-071 calibration. No missing observation
    is treated as zero, and temporal association is not a causal result.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    as_of = as_of.astimezone(timezone.utc)
    facts = sorted(
        (e for e in events if e.recorded_at <= as_of),
        key=lambda e: (e.recorded_at, e.sequence or 0, str(e.id)),
    )
    last_seen: dict[UUID, datetime] = {}
    last_fact: dict[UUID, HistoryEvent] = {}
    user_facts: list[HistoryEvent] = []
    for event in facts:
        if event.task_id is None:
            continue
        last_seen[event.task_id] = event.recorded_at
        last_fact[event.task_id] = event
        if event.source is HistorySource.USER:
            user_facts.append(event)

    trends: list[dict] = []

    def trend(code: str, description: str, count: int, distinct: int,
              *, work_type_id: str | None = None, scope: str = "ALL") -> None:
        if count < MIN_SAMPLES or distinct < MIN_SAMPLES:
            return
        trends.append({
            "code": code, "scope": scope, "work_type_id": work_type_id,
            "sample_size": count, "distinct_tasks": distinct,
            "minimum_samples": MIN_SAMPLES, "uncertainty": "LIMITED",
            "description": description, "data_quality": "UNVERIFIED",
        })

    for code, event_types, text in (
        ("ESTIMATES_REVISED", {"TASK_ESTIMATE_CHANGED", "SEGMENT_ESTIMATE_CHANGED"},
         "Des estimations ont été révisées dans l'historique observé, sans indiquer pourquoi."),
        ("SEGMENTATION_OBSERVED", {"SEGMENT_ADDED"},
         "Des segments ont été créés pour plusieurs tâches; leur effet sur le démarrage est inconnu."),
    ):
        selected = [e for e in user_facts if e.event_type in event_types]
        trend(code, text, len(selected), len({e.task_id for e in selected}))

    reasons: dict[str, list[HistoryEvent]] = defaultdict(list)
    for event in user_facts:
        if event.reason_code in DECLARED_REASONS:
            reasons[event.reason_code].append(event)
    for reason, values in sorted(reasons.items()):
        trend("DECLARED_" + reason,
              "Le motif « " + reason + " » a été déclaré; il ne prouve pas la cause.",
              len(values), len({e.task_id for e in values}))

    finished_by_type: dict[UUID | None, list[WorkSession]] = defaultdict(list)
    for session in sessions:
        if (session.status is SessionStatus.FINISHED and session.finished_at
                and session.finished_at <= as_of):
            finished_by_type[session.work_type_id].append(session)
    for work_type_id, values in sorted(
        finished_by_type.items(), key=lambda p: str(p[0])
    ):
        count = sum(s.interruptions > 0 for s in values)
        distinct = len({s.task_id for s in values})
        trend(
            "INTERRUPTION_FREQUENCY",
            str(count) + " session(s) sur " + str(len(values))
            + " terminée(s) comportent une interruption déclarée; la couverture est inconnue.",
            len(values), distinct, work_type_id=str(work_type_id) if work_type_id else None,
            scope="WORK_TYPE",
        )

    for row in calibration:
        sample = row.get("completed_unit_samples", 0)
        if not row.get("calibration_ready") or not isinstance(sample, int) or sample < MIN_SAMPLES:
            continue
        estimate, observed = row.get("median_estimated_minutes"), row.get("median_observed_minutes")
        if estimate is None or observed is None:
            continue
        trend(
            "ESTIMATE_VS_OBSERVED",
            "Médianes des unités terminées : estimation " + str(estimate)
            + " min, temps actif enregistré " + str(observed)
            + " min. Du travail non enregistré peut manquer.",
            sample, sample,
            work_type_id=str(row.get("work_type_id")) if row.get("work_type_id") else None,
            scope="WORK_TYPE",
        )

    by_task_sessions: dict[UUID, list[WorkSession]] = defaultdict(list)
    for session in sessions:
        if session.started_at <= as_of:
            by_task_sessions[session.task_id].append(session)
    interventions: list[dict] = []

    def propose(task: Task, code: str, observation: str, suggestion: str,
                quality: str = "UNVERIFIED") -> None:
        interventions.append({
            "task_id": str(task.id), "task_title": task.title,
            "code": code, "observation": observation, "suggestion": suggestion,
            "data_quality": quality, "requires_confirmation": True,
        })

    for task in sorted(tasks, key=lambda t: (t.title.casefold(), str(t.id))):
        if task.status not in OPEN:
            continue
        last = last_seen.get(task.id)
        if last is not None and last < as_of - timedelta(days=QUIET_DAYS):
            propose(task, "REVISIT_QUIET",
                    "Aucune interaction instrumentée depuis au moins 14 jours.",
                    "Choisir explicitement : remettre en circulation, reporter, fixer une revue ou envisager l'abandon.")
        elif last is None and task.created_at < as_of - timedelta(days=QUIET_DAYS):
            propose(task, "REVIEW_UNKNOWN_ACTIVITY",
                    "Historique d'interaction indisponible; l'activité réelle est inconnue.",
                    "Vérifier si cet élément doit revenir en revue ou recevoir une prochaine date.",
                    "UNKNOWN")

        recent = last_fact.get(task.id)
        if recent is not None and recent.source is HistorySource.USER:
            if recent.reason_code == "MISSING_INFORMATION":
                propose(task, "CLARIFY_INFORMATION",
                        "Une information manquante a été déclarée lors de la dernière interaction.",
                        "Proposer une question précise avant de reprendre.")
            elif recent.reason_code == "BLOCKED":
                propose(task, "REVIEW_BLOCKER",
                        "Un blocage a été déclaré lors de la dernière interaction.",
                        "Vérifier ce qui reste bloqué et choisir une prochaine action courte.")

        if any(s.status is SessionStatus.PAUSED for s in by_task_sessions.get(task.id, ())):
            propose(task, "RESUME_PAUSED",
                    "Une session déclarée reste en pause.",
                    "Consulter le point de reprise puis choisir si et quand relancer la session.")
        if (task.status is not TaskStatus.INBOX and task.estimated_minutes is not None
                and task.estimated_minutes >= 90 and task.id not in decomposed_ids):
            propose(task, "SPLIT_LARGE_UNIT",
                    "Estimation actuelle d'au moins 90 minutes, sans segments enregistrés.",
                    "Envisager une première petite action ou une décomposition avant de planifier.")
    return {
        "as_of": as_of, "minimum_samples": MIN_SAMPLES,
        "data_quality": "UNVERIFIED", "trends": trends,
        "interventions": interventions, "changes_applied": False,
        "limitations": [
            "Les tendances décrivent des associations, jamais une cause ou un diagnostic.",
            "Les sessions et l'historique peuvent omettre du travail non enregistré.",
            "Les suggestions ne changent ni tâches, ni priorités, ni calendrier.",
        ],
    }
