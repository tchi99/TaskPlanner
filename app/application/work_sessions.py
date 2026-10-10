"""TP-071 orchestration: session transitions + append-only facts in a single UoW."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from uuid import UUID, uuid4

from app.application.history import HistoryEvent, HistorySource
from app.application.uow import UnitOfWork
from app.domain import SegmentStatus, TaskStatus
from app.domain.task_rules import NextActionType
from app.domain.work_sessions import SessionConflict, SessionStatus, WorkSession, utc


def _now(value: datetime | None) -> datetime:
    return utc(value or datetime.now(timezone.utc))


def _aggregate(uow: UnitOfWork, task_id: UUID):
    value = uow.tasks.get_aggregate(task_id)
    if value is None:
        raise LookupError("task not found")
    return value


def _open_target(aggregate, segment_id: UUID | None) -> None:
    if aggregate.task.status not in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
        raise ValueError("work sessions require a clarified, open task")
    if segment_id is None:
        if aggregate.segments:
            raise ValueError("decomposed work must target a segment")
    else:
        segment = next((s for s in aggregate.segments if s.id == segment_id), None)
        if segment is None or segment.status not in (SegmentStatus.TODO, SegmentStatus.IN_PROGRESS):
            raise ValueError("work segment must exist and remain open")


def _history(value: WorkSession, kind: str, at: datetime, reason_code: str | None) -> HistoryEvent:
    return HistoryEvent(
        id=uuid4(), occurred_at=at, recorded_at=at,
        entity_type="SEGMENT" if value.segment_id else "TASK",
        entity_id=value.segment_id or value.task_id, task_id=value.task_id,
        event_type=kind, schema_version=1, source=HistorySource.USER,
        reason_code=reason_code, correlation_id=uuid4(), causation_id=None,
        payload={
            "session_id": str(value.id),
            "status": value.status.value,
            "active_seconds": value.active_seconds,
            "interruptions": value.interruptions,
        },
    )


def start_session(
    uow: UnitOfWork, task_id: UUID, *, segment_id: UUID | None = None,
    planned_minutes: int | None = None, now: datetime | None = None,
) -> WorkSession:
    at = _now(now)
    with uow:
        aggregate = _aggregate(uow, task_id)
        _open_target(aggregate, segment_id)
        action = aggregate.next_action()
        if not action or action.action_type not in (NextActionType.WORK_ON_TASK, NextActionType.WORK_ON_SEGMENT):
            raise ValueError("no executable next action for this task")
        if action.target_id != (segment_id or task_id):
            raise SessionConflict("next action changed; reload before starting")
        if uow.work_sessions.get_active() is not None:
            raise SessionConflict("another work session is already active")
        estimate = (aggregate.task.estimated_minutes if segment_id is None
                    else next(s.estimated_minutes for s in aggregate.segments if s.id == segment_id))
        work_type_id = (aggregate.effective_task_work_type().work_type_id if segment_id is None
                        else aggregate.effective_segment_work_type(segment_id).work_type_id)
        value = WorkSession.start(task_id, segment_id, at, work_type_id,
                                  estimate, planned_minutes)
        uow.work_sessions.add(value)
        uow.history.append(_history(value, "WORK_SESSION_STARTED", at, None))
        uow.commit()
        return value


def change_session(
    uow: UnitOfWork, session_id: UUID, *, action: str,
    expected_revision: int, reason_code: str | None = None,
    now: datetime | None = None,
) -> WorkSession:
    at = _now(now)
    if expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    with uow:
        current = uow.work_sessions.get(session_id)
        if current is None:
            raise LookupError("work session not found")
        if current.revision != expected_revision:
            raise SessionConflict("session revision changed; reload before updating")
        if action == "resume":
            _open_target(_aggregate(uow, current.task_id), current.segment_id)
            if uow.work_sessions.get_active() is not None:
                raise SessionConflict("another work session is already active")
            updated = current.resume(at)
        elif action == "pause":
            updated = current.pause(at)
        elif action == "finish":
            updated = current.finish(at)
        else:
            raise ValueError("unsupported session transition")
        uow.work_sessions.save(updated, expected_revision)
        uow.history.append(_history(updated, "WORK_SESSION_" + {
            "pause": "PAUSED", "resume": "RESUMED", "finish": "FINISHED",
        }[action], at, reason_code))
        uow.commit()
        return updated


def read_task_observation(
    uow: UnitOfWork, task_id: UUID, *, now: datetime | None = None,
) -> dict:
    at = _now(now)
    with uow:
        aggregate = _aggregate(uow, task_id)
        values = uow.work_sessions.list_task(task_id)
        estimate = aggregate.effective_estimate()
        recorded = sum(s.active_seconds for s in values)
        provisional = sum(s.observed_seconds(at) - s.active_seconds
                          for s in values if s.status is SessionStatus.ACTIVE)
        return {
            "sessions": values,
            "estimate_minutes": estimate.total_minutes,
            "estimate_incomplete": estimate.incomplete,
            "recorded_active_seconds": recorded,
            "provisional_active_seconds": provisional,
            "observed_minutes": round(recorded / 60, 2),
            "difference_minutes": (
                round(recorded / 60 - estimate.total_minutes, 2)
                if estimate.total_minutes is not None else None
            ),
            "has_open_sessions": any(s.status is not SessionStatus.FINISHED for s in values),
            "coverage": "UNVERIFIED",
            "disclaimer": "Unrecorded work is unknown; observed time is not elapsed task time.",
        }


def _is_completed(aggregate, segment_id: UUID | None) -> bool:
    if segment_id is None:
        return not aggregate.segments and aggregate.task.status is TaskStatus.DONE
    return any(s.id == segment_id and s.status is SegmentStatus.DONE
               for s in aggregate.segments)


def descriptive_statistics(uow: UnitOfWork) -> list[dict]:
    """Only finished sessions; completed *units* for estimate comparison.

    Data coverage is unverified even for completed units: missing sessions are not zero.
    """
    with uow:
        sessions = uow.work_sessions.list_all()
        grouped: dict[tuple[UUID | None, str], list[WorkSession]] = {}
        for session in sessions:
            context = "SEGMENT" if session.segment_id else "TASK"
            grouped.setdefault((session.work_type_id, context), []).append(session)
        aggregates = {}
        results = []
        for (type_id, context), items in sorted(grouped.items(), key=lambda pair: str(pair[0])):
            finished = [s for s in items if s.status is SessionStatus.FINISHED]
            units: dict[tuple[UUID, UUID | None], list[WorkSession]] = {}
            for session in items:
                units.setdefault((session.task_id, session.segment_id), []).append(session)
            comparisons: list[tuple[int, float]] = []
            for (task_id, segment_id), unit_sessions in units.items():
                if any(s.status is not SessionStatus.FINISHED for s in unit_sessions):
                    continue
                if task_id not in aggregates:
                    aggregates[task_id] = _aggregate(uow, task_id)
                if not _is_completed(aggregates[task_id], segment_id):
                    continue
                estimates = {s.estimated_minutes for s in unit_sessions}
                if len(estimates) != 1 or None in estimates:
                    continue
                comparisons.append((unit_sessions[0].estimated_minutes,
                                    round(sum(s.active_seconds for s in unit_sessions) / 60, 2)))
            ready = len(comparisons) >= 3
            deviations = [round(observed - estimate, 2) for estimate, observed in comparisons]
            results.append({
                "work_type_id": type_id,
                "work_type_name": (uow.work_types.get(type_id).name
                                   if type_id and uow.work_types.get(type_id) else "Non classé"),
                "context": context,
                "finished_sessions": len(finished),
                "median_session_minutes": (
                    round(median(s.active_seconds / 60 for s in finished), 2)
                    if finished else None
                ),
                "interruption_frequency": (
                    round(sum(s.interruptions > 0 for s in finished) / len(finished), 3)
                    if finished else None
                ),
                "completed_unit_samples": len(comparisons),
                "minimum_samples": 3,
                "calibration_ready": ready,
                "median_estimated_minutes": (
                    round(median(a for a, _ in comparisons), 2) if ready else None
                ),
                "median_observed_minutes": (
                    round(median(b for _, b in comparisons), 2) if ready else None
                ),
                "deviations_minutes": sorted(deviations) if ready else [],
                "coverage": "UNVERIFIED",
            })
        return results
