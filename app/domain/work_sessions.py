"""TP-071: explicit, measured work intervals; never infer activity from task status."""
from __future__ import annotations

from dataclasses import dataclass, replace, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class SessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"


class SessionConflict(Exception):
    """Stale revision, illegal transition or another active session."""


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session timestamps must include timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class WorkSession:
    task_id: UUID
    segment_id: UUID | None
    started_at: datetime
    active_since: datetime | None
    finished_at: datetime | None = None
    active_seconds: int = 0
    interruptions: int = 0
    status: SessionStatus = SessionStatus.ACTIVE
    revision: int = 1
    work_type_id: UUID | None = None
    estimated_minutes: int | None = None
    planned_minutes: int | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        start = utc(self.started_at)
        if self.active_since is not None and utc(self.active_since) < start:
            raise ValueError("active_since precedes start")
        if self.finished_at is not None and utc(self.finished_at) < start:
            raise ValueError("finish precedes start")
        if self.status is SessionStatus.ACTIVE and (self.active_since is None or self.finished_at):
            raise ValueError("active session needs active_since and no finish")
        if self.status is SessionStatus.PAUSED and (self.active_since or self.finished_at):
            raise ValueError("paused session cannot count active time")
        if self.status is SessionStatus.FINISHED and (self.active_since or not self.finished_at):
            raise ValueError("finished session needs finished_at")
        if self.active_seconds < 0 or self.interruptions < 0 or self.revision < 1:
            raise ValueError("invalid session counters")
        for value in (self.estimated_minutes, self.planned_minutes):
            if value is not None and value <= 0:
                raise ValueError("minutes must be positive")

    @classmethod
    def start(cls, task_id: UUID, segment_id: UUID | None, at: datetime,
              work_type_id: UUID | None, estimated_minutes: int | None,
              planned_minutes: int | None = None) -> "WorkSession":
        now = utc(at)
        return cls(task_id=task_id, segment_id=segment_id, started_at=now,
                   active_since=now, work_type_id=work_type_id,
                   estimated_minutes=estimated_minutes, planned_minutes=planned_minutes,
                   id=uuid4())

    def observed_seconds(self, at: datetime) -> int:
        now = utc(at)
        if self.active_since is None:
            return self.active_seconds
        if now < self.active_since:
            raise ValueError("clock precedes session interval")
        return self.active_seconds + int((now - utc(self.active_since)).total_seconds())

    def pause(self, at: datetime) -> "WorkSession":
        if self.status is not SessionStatus.ACTIVE:
            raise SessionConflict("only active sessions can be paused")
        return replace(self, active_seconds=self.observed_seconds(at),
                       active_since=None, interruptions=self.interruptions + 1,
                       status=SessionStatus.PAUSED, revision=self.revision + 1)

    def resume(self, at: datetime) -> "WorkSession":
        if self.status is not SessionStatus.PAUSED:
            raise SessionConflict("only paused sessions can resume")
        now = utc(at)
        if now < utc(self.started_at):
            raise ValueError("clock precedes session start")
        return replace(self, active_since=now, status=SessionStatus.ACTIVE,
                       revision=self.revision + 1)

    def finish(self, at: datetime) -> "WorkSession":
        if self.status is SessionStatus.FINISHED:
            raise SessionConflict("session is already finished")
        now = utc(at)
        if now < utc(self.started_at):
            raise ValueError("clock precedes session start")
        return replace(self, active_seconds=self.observed_seconds(now),
                       active_since=None, finished_at=now,
                       status=SessionStatus.FINISHED, revision=self.revision + 1)

    def guardrail(self, at: datetime) -> str | None:
        if self.status is not SessionStatus.ACTIVE or self.planned_minutes is None:
            return None
        if self.observed_seconds(at) >= self.planned_minutes * 60:
            return "PLANNED_BLOCK_REACHED"
        return None
