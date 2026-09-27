from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_positive_minutes(value: int | None, field_name: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _require_non_negative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be zero or greater")


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


class ProtectionLevel(StrEnum):
    PROTECTED = "PROTECTED"
    REPLANNABLE = "REPLANNABLE"
    FLEXIBLE = "FLEXIBLE"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class TaskStatus(StrEnum):
    INBOX = "INBOX"
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class SegmentStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ConstraintKind(StrEnum):
    DEADLINE = "DEADLINE"
    TIME_BLOCK = "TIME_BLOCK"
    CAPACITY = "CAPACITY"
    USER_RULE = "USER_RULE"


class DecisionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class WorkType:
    name: str
    description: str | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.name, "name")


@dataclass(frozen=True, slots=True)
class Project:
    title: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.title, "title")


@dataclass(frozen=True, slots=True)
class Task:
    title: str
    project_id: UUID | None = None
    notes: str | None = None
    status: TaskStatus = TaskStatus.TODO
    protection: ProtectionLevel = ProtectionLevel.REPLANNABLE
    work_type_id: UUID | None = None
    estimated_minutes: int | None = None
    due_at: datetime | None = None
    created_at: datetime = field(default_factory=_utc_now)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        _require_positive_minutes(self.estimated_minutes, "estimated_minutes")
        _require_aware(self.due_at, "due_at")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class TaskSegment:
    task_id: UUID
    title: str
    status: SegmentStatus = SegmentStatus.TODO
    position: int = 0
    work_type_id: UUID | None = None
    estimated_minutes: int | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        if not isinstance(self.status, SegmentStatus):
            raise ValueError("status must be a SegmentStatus")
        _require_non_negative(self.position, "position")
        _require_positive_minutes(self.estimated_minutes, "estimated_minutes")


@dataclass(frozen=True, slots=True)
class Constraint:
    title: str
    kind: ConstraintKind
    protection: ProtectionLevel = ProtectionLevel.PROTECTED
    target_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    details: str | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        _require_aware(self.starts_at, "starts_at")
        _require_aware(self.ends_at, "ends_at")
        if self.starts_at is not None and self.ends_at is not None:
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must be after starts_at")


@dataclass(frozen=True, slots=True)
class PlanningOption:
    label: str
    rationale: str
    affected_item_ids: tuple[UUID, ...] = ()
    consequences: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_text(self.label, "label")
        _require_text(self.rationale, "rationale")


@dataclass(frozen=True, slots=True)
class PlanningProposal:
    options: tuple[PlanningOption, ...]
    facts: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_utc_now)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError("a planning proposal must contain at least one option")
        _require_aware(self.created_at, "created_at")
        option_ids = [option.id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("planning option ids must be unique within a proposal")


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    proposal_id: UUID
    outcome: DecisionOutcome
    option_id: UUID | None = None
    decided_at: datetime = field(default_factory=_utc_now)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        _require_aware(self.decided_at, "decided_at")
        if self.outcome is DecisionOutcome.ACCEPTED and self.option_id is None:
            raise ValueError("an accepted decision must select an option")
        if self.outcome is DecisionOutcome.REJECTED and self.option_id is not None:
            raise ValueError("a rejected decision must not select an option")

    def validate_against(self, proposal: PlanningProposal) -> None:
        if proposal.id != self.proposal_id:
            raise ValueError("decision does not reference the supplied proposal")
        if self.outcome is DecisionOutcome.ACCEPTED:
            valid_option_ids = {option.id for option in proposal.options}
            if self.option_id not in valid_option_ids:
                raise ValueError("selected option does not belong to the proposal")
