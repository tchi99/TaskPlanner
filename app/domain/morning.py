"""Deterministic, read-only morning briefing from existing task and capacity facts.

There are no day assignments or accepted plans yet: a weekly comparison of *all*
open work is deliberately labelled hypothetical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.capacity import (
    AvailabilityBlock, WeeklyCapacityEvaluation, evaluate_week,
)
from app.domain.model import ProtectionLevel, TaskStatus
from app.domain.planning import effective_task_protection
from app.domain.task_rules import TaskAggregate


class DueStatus(StrEnum):
    OVERDUE = "OVERDUE"
    TODAY = "TODAY"
    LATER = "LATER"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class MorningItem:
    task_id: UUID
    title: str
    protection: ProtectionLevel
    due_at: datetime | None
    due_status: DueStatus
    next_action: str | None


@dataclass(frozen=True, slots=True)
class MorningDecision:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MorningBrief:
    day: date
    timezone_name: str
    week_start: date
    today_available_minutes: int
    manual_block_count: int
    open_task_count: int
    inbox_count: int
    weekly_if_all_open: WeeklyCapacityEvaluation
    must_review: tuple[MorningItem, ...]
    may_slip: tuple[MorningItem, ...]
    decisions: tuple[MorningDecision, ...]


def build_morning_brief(
    day: date,
    timezone_name: str,
    blocks: Sequence[AvailabilityBlock],
    aggregates: Sequence[TaskAggregate],
    inbox_count: int,
) -> MorningBrief:
    """Summarize facts without selecting a day plan or suggesting an accepted move."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid IANA timezone") from exc
    if inbox_count < 0:
        raise ValueError("inbox_count cannot be negative")
    monday = day - timedelta(days=day.weekday())
    for aggregate in aggregates:
        if aggregate.task.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            raise ValueError("morning candidates must be open clarified tasks")
    weekly = evaluate_week(monday, blocks, aggregates)

    # Clip manual availability to the requested local civil day, including
    # overnight blocks and DST transitions. This is *capacity*, not a booking.
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    today_minutes = sum(
        max(0, int((
            min(block.ends_at.astimezone(timezone.utc), end)
            - max(block.starts_at.astimezone(timezone.utc), start)
        ).total_seconds() // 60))
        for block in blocks
    )

    must_review: list[MorningItem] = []
    may_slip: list[MorningItem] = []
    for aggregate in aggregates:
        task = aggregate.task
        protection = effective_task_protection(aggregate)
        due_day = task.due_at.astimezone(zone).date() if task.due_at else None
        due_status = (
            DueStatus.NONE if due_day is None
            else DueStatus.OVERDUE if due_day < day
            else DueStatus.TODAY if due_day == day
            else DueStatus.LATER
        )
        action = aggregate.next_action()
        item = MorningItem(
            task_id=task.id, title=task.title, protection=protection,
            due_at=task.due_at, due_status=due_status,
            next_action=action.label if action else None,
        )
        if protection is ProtectionLevel.PROTECTED or due_status in {DueStatus.OVERDUE, DueStatus.TODAY}:
            must_review.append(item)
        else:
            # Neither a protected whole task nor an item with an imminent/late
            # deadline may be advertised as potentially deferrable.
            may_slip.append(item)

    order = {DueStatus.OVERDUE: 0, DueStatus.TODAY: 1, DueStatus.LATER: 2, DueStatus.NONE: 3}
    sort_key = lambda item: (order[item.due_status], item.title.casefold(), str(item.task_id))
    must_review.sort(key=sort_key)
    may_slip.sort(key=sort_key)

    decisions: list[MorningDecision] = []
    if any(item.due_status is DueStatus.OVERDUE for item in must_review):
        decisions.append(MorningDecision("OVERDUE", "Examiner les échéances dépassées sans les déplacer automatiquement."))
    if any(item.due_status is DueStatus.TODAY for item in must_review):
        decisions.append(MorningDecision("TODAY_DUE", "Choisir comment traiter les échéances d'aujourd'hui."))
    if not blocks:
        decisions.append(MorningDecision("NO_BLOCKS", "Renseigner les disponibilités manuelles de la semaine avant de conclure sur la charge."))
    elif weekly.status.value == "OVER_CAPACITY":
        decisions.append(MorningDecision("POTENTIAL_OVERLOAD", "Comparer une sélection réaliste à la capacité : toutes les tâches ouvertes dépasseraient les blocs connus."))
    if weekly.unestimated_units:
        decisions.append(MorningDecision("UNKNOWN_ESTIMATES", "Clarifier les estimations inconnues avant de juger la faisabilité."))
    if inbox_count:
        decisions.append(MorningDecision("INBOX", "Clarifier les captures de l'Inbox qui nécessitent une décision."))
    if aggregates:
        decisions.append(MorningDecision("SELECT_TODAY", "Choisir explicitement le travail du jour; aucune tâche n'est affectée automatiquement."))

    return MorningBrief(
        day=day, timezone_name=timezone_name, week_start=monday,
        today_available_minutes=today_minutes, manual_block_count=len(blocks),
        open_task_count=len(aggregates), inbox_count=inbox_count,
        weekly_if_all_open=weekly,
        must_review=tuple(must_review), may_slip=tuple(may_slip),
        decisions=tuple(decisions),
    )
