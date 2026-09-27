from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from .facts import (
    DomainEntityType,
    DomainFact,
    DomainFactType,
    EstimateChanged,
    FactRole,
    MutationResult,
    SegmentPosition,
    SegmentStatusChanged,
    TaskStatusChanged,
    WorkTypeChanged,
)
from .model import (
    Project,
    ProjectStatus,
    ProtectionLevel,
    SegmentStatus,
    Task,
    TaskSegment,
    TaskStatus,
)


_TASK_TERMINAL = {TaskStatus.DONE, TaskStatus.CANCELLED}
_TASK_OPEN = {TaskStatus.INBOX, TaskStatus.TODO, TaskStatus.IN_PROGRESS}
_SEGMENT_OPEN = {SegmentStatus.TODO, SegmentStatus.IN_PROGRESS}
_SEGMENT_TERMINAL = {SegmentStatus.DONE, SegmentStatus.CANCELLED}


class EstimateSource(StrEnum):
    TASK = "TASK"
    SEGMENTS = "SEGMENTS"


@dataclass(frozen=True, slots=True)
class EffectiveEstimate:
    source: EstimateSource
    known_subtotal_minutes: int
    unestimated_units: int
    total_minutes: int | None
    incomplete: bool


class NextActionType(StrEnum):
    CLARIFY_TASK = "CLARIFY_TASK"
    WORK_ON_TASK = "WORK_ON_TASK"
    WORK_ON_SEGMENT = "WORK_ON_SEGMENT"
    REVIEW_COMPLETION = "REVIEW_COMPLETION"


@dataclass(frozen=True, slots=True)
class NextAction:
    action_type: NextActionType
    target_id: UUID
    label: str


class WorkTypeOrigin(StrEnum):
    SEGMENT_OVERRIDE = "SEGMENT_OVERRIDE"
    TASK_INHERITED = "TASK_INHERITED"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class EffectiveWorkType:
    work_type_id: UUID | None
    origin: WorkTypeOrigin


def can_complete_project(task_statuses: Iterable[TaskStatus]) -> bool:
    return not any(status in _TASK_OPEN for status in task_statuses)


def complete_project(project: Project, task_statuses: Iterable[TaskStatus]) -> Project:
    if project.status is ProjectStatus.COMPLETED:
        return project
    if project.status is not ProjectStatus.ACTIVE:
        raise ValueError("only an active project can be completed")
    if not can_complete_project(task_statuses):
        raise ValueError("project cannot be completed while work remains open")
    return replace(project, status=ProjectStatus.COMPLETED)


@dataclass(frozen=True, slots=True)
class TaskAggregate:
    task: Task
    segments: tuple[TaskSegment, ...] = ()

    def __post_init__(self) -> None:
        self._validate_segments(self.segments)
        if self.task.status is TaskStatus.INBOX and self.segments:
            raise ValueError("an inbox task cannot have segments")

    def _validate_segments(self, segments: Sequence[TaskSegment]) -> None:
        ids: set[UUID] = set()
        positions: set[int] = set()
        for segment in segments:
            if segment.task_id != self.task.id:
                raise ValueError("segment task_id must match the aggregate task")
            if segment.id in ids:
                raise ValueError("segment ids must be unique within a task")
            if segment.position in positions:
                raise ValueError("segment positions must be unique within a task")
            ids.add(segment.id)
            positions.add(segment.position)

    def _ordered(self) -> tuple[TaskSegment, ...]:
        return tuple(sorted(self.segments, key=lambda segment: segment.position))

    def _segment(self, segment_id: UUID) -> TaskSegment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        raise ValueError("segment does not belong to the task")

    def _replace_segment(self, replacement: TaskSegment) -> TaskAggregate:
        if replacement.task_id != self.task.id:
            raise ValueError("segment task_id is immutable")
        segments = tuple(
            replacement if segment.id == replacement.id else segment
            for segment in self.segments
        )
        return TaskAggregate(task=self.task, segments=segments)

    def _ensure_structure_mutable(self) -> None:
        if self.task.status in _TASK_TERMINAL:
            raise ValueError("terminal task must be reopened before changing work structure")
        if self.task.status is TaskStatus.INBOX:
            raise ValueError("task must be clarified before changing work structure")

    def clarify(self) -> MutationResult[TaskAggregate]:
        if self.task.status is not TaskStatus.INBOX:
            raise ValueError("only an inbox task can be clarified")
        updated = replace(self.task, status=TaskStatus.TODO)
        aggregate = TaskAggregate(updated, self.segments)
        return MutationResult(
            aggregate,
            (
                self._task_fact(
                    DomainFactType.TASK_CLARIFIED,
                    FactRole.DIRECT,
                    TaskStatusChanged(TaskStatus.INBOX, TaskStatus.TODO),
                ),
            ),
        )

    def start(self) -> MutationResult[TaskAggregate]:
        if self.task.status is not TaskStatus.TODO:
            raise ValueError("only a todo task can be started")
        if self.segments:
            raise ValueError("a decomposed task progresses through its segments")
        updated = replace(self.task, status=TaskStatus.IN_PROGRESS)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_STARTED,
                    FactRole.DIRECT,
                    TaskStatusChanged(TaskStatus.TODO, TaskStatus.IN_PROGRESS),
                ),
            ),
        )

    def complete(self) -> MutationResult[TaskAggregate]:
        if self.task.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            raise ValueError("only an open clarified task can be completed")
        if any(segment.status in _SEGMENT_OPEN for segment in self.segments):
            raise ValueError("task cannot be completed while a segment remains open")
        updated = replace(self.task, status=TaskStatus.DONE)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_COMPLETED,
                    FactRole.DIRECT,
                    TaskStatusChanged(self.task.status, TaskStatus.DONE),
                ),
            ),
        )

    def cancel(self) -> MutationResult[TaskAggregate]:
        if self.task.status not in _TASK_OPEN:
            raise ValueError("only a non-terminal task can be cancelled")
        updated = replace(self.task, status=TaskStatus.CANCELLED)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_CANCELLED,
                    FactRole.DIRECT,
                    TaskStatusChanged(self.task.status, TaskStatus.CANCELLED),
                ),
            ),
        )

    def reopen(self) -> MutationResult[TaskAggregate]:
        if self.task.status not in _TASK_TERMINAL:
            raise ValueError("only a terminal task can be reopened")
        progressed_segment_exists = any(
            segment.status is not SegmentStatus.TODO for segment in self.segments
        )
        target_status = (
            TaskStatus.IN_PROGRESS if progressed_segment_exists else TaskStatus.TODO
        )
        updated = replace(self.task, status=target_status)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_REOPENED,
                    FactRole.DIRECT,
                    TaskStatusChanged(self.task.status, target_status),
                ),
            ),
        )

    def change_task_estimate(
        self, estimated_minutes: int | None
    ) -> MutationResult[TaskAggregate]:
        if estimated_minutes is not None and estimated_minutes <= 0:
            raise ValueError("estimated_minutes must be greater than zero")
        if self.task.estimated_minutes == estimated_minutes:
            return MutationResult(self)
        before = self.task.estimated_minutes
        updated = replace(self.task, estimated_minutes=estimated_minutes)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_ESTIMATE_CHANGED,
                    FactRole.DIRECT,
                    EstimateChanged(before, estimated_minutes),
                ),
            ),
        )

    def change_task_work_type(
        self, work_type_id: UUID | None
    ) -> MutationResult[TaskAggregate]:
        if self.task.work_type_id == work_type_id:
            return MutationResult(self)
        before = self.task.work_type_id
        updated = replace(self.task, work_type_id=work_type_id)
        return MutationResult(
            TaskAggregate(updated, self.segments),
            (
                self._task_fact(
                    DomainFactType.TASK_WORK_TYPE_CHANGED,
                    FactRole.DIRECT,
                    WorkTypeChanged(before, work_type_id),
                ),
            ),
        )

    def add_segment(
        self,
        title: str,
        *,
        estimated_minutes: int | None = None,
        work_type_id: UUID | None = None,
        position: int | None = None,
        segment_id: UUID | None = None,
    ) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        if position is None:
            position = max(
                (segment.position for segment in self.segments), default=-1
            ) + 1
        if any(segment.position == position for segment in self.segments):
            raise ValueError("segment position must be unique within a task")
        segment = TaskSegment(
            task_id=self.task.id,
            title=title,
            position=position,
            work_type_id=work_type_id,
            estimated_minutes=estimated_minutes,
            id=segment_id or uuid4(),
        )
        aggregate = TaskAggregate(self.task, (*self.segments, segment))
        return MutationResult(
            aggregate,
            (
                self._segment_fact(
                    segment,
                    DomainFactType.SEGMENT_ADDED,
                    FactRole.DIRECT,
                    SegmentPosition(segment.position),
                ),
            ),
        )

    def remove_segment(self, segment_id: UUID) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        segment = self._segment(segment_id)
        if segment.status is not SegmentStatus.TODO:
            raise ValueError("only an unstarted todo segment can be removed")
        remaining = tuple(item for item in self.segments if item.id != segment_id)
        aggregate = TaskAggregate(self.task, remaining)
        return MutationResult(
            aggregate,
            (
                self._segment_fact(
                    segment,
                    DomainFactType.SEGMENT_REMOVED,
                    FactRole.DIRECT,
                    SegmentPosition(segment.position),
                ),
            ),
        )

    def reorder_segments(
        self, ordered_segment_ids: Sequence[UUID]
    ) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        current_ids = {segment.id for segment in self.segments}
        if len(ordered_segment_ids) != len(self.segments):
            raise ValueError("reorder must include every segment exactly once")
        if len(set(ordered_segment_ids)) != len(ordered_segment_ids):
            raise ValueError("reorder cannot contain duplicate segment ids")
        if set(ordered_segment_ids) != current_ids:
            raise ValueError("reorder must include only segments from the task")

        by_id = {segment.id: segment for segment in self.segments}
        reordered = tuple(
            replace(by_id[segment_id], position=position)
            for position, segment_id in enumerate(ordered_segment_ids)
        )
        if reordered == self._ordered():
            return MutationResult(self)
        # ADR-0005 allows reordering history to be added with a later command.
        return MutationResult(TaskAggregate(self.task, reordered))

    def start_segment(self, segment_id: UUID) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        segment = self._segment(segment_id)
        if segment.status is not SegmentStatus.TODO:
            raise ValueError("only a todo segment can be started")
        updated_segment = replace(segment, status=SegmentStatus.IN_PROGRESS)
        aggregate = self._replace_segment(updated_segment)
        facts = [
            self._segment_fact(
                updated_segment,
                DomainFactType.SEGMENT_STARTED,
                FactRole.DIRECT,
                SegmentStatusChanged(
                    SegmentStatus.TODO, SegmentStatus.IN_PROGRESS
                ),
            )
        ]
        aggregate, propagated = aggregate._progress_parent_if_needed()
        facts.extend(propagated)
        return MutationResult(aggregate, tuple(facts))

    def complete_segment(self, segment_id: UUID) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        segment = self._segment(segment_id)
        if segment.status not in {SegmentStatus.TODO, SegmentStatus.IN_PROGRESS}:
            raise ValueError("only an open segment can be completed")
        before = segment.status
        updated_segment = replace(segment, status=SegmentStatus.DONE)
        aggregate = self._replace_segment(updated_segment)
        facts = [
            self._segment_fact(
                updated_segment,
                DomainFactType.SEGMENT_COMPLETED,
                FactRole.DIRECT,
                SegmentStatusChanged(before, SegmentStatus.DONE),
            )
        ]
        aggregate, propagated = aggregate._progress_parent_if_needed()
        facts.extend(propagated)
        return MutationResult(aggregate, tuple(facts))

    def cancel_segment(self, segment_id: UUID) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        segment = self._segment(segment_id)
        if segment.status not in {SegmentStatus.TODO, SegmentStatus.IN_PROGRESS}:
            raise ValueError("only an open segment can be cancelled")
        before = segment.status
        updated_segment = replace(segment, status=SegmentStatus.CANCELLED)
        aggregate = self._replace_segment(updated_segment)
        return MutationResult(
            aggregate,
            (
                self._segment_fact(
                    updated_segment,
                    DomainFactType.SEGMENT_CANCELLED,
                    FactRole.DIRECT,
                    SegmentStatusChanged(before, SegmentStatus.CANCELLED),
                ),
            ),
        )

    def change_segment_estimate(
        self, segment_id: UUID, estimated_minutes: int | None
    ) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        if estimated_minutes is not None and estimated_minutes <= 0:
            raise ValueError("estimated_minutes must be greater than zero")
        segment = self._segment(segment_id)
        if segment.estimated_minutes == estimated_minutes:
            return MutationResult(self)
        before = segment.estimated_minutes
        updated_segment = replace(segment, estimated_minutes=estimated_minutes)
        aggregate = self._replace_segment(updated_segment)
        return MutationResult(
            aggregate,
            (
                self._segment_fact(
                    updated_segment,
                    DomainFactType.SEGMENT_ESTIMATE_CHANGED,
                    FactRole.DIRECT,
                    EstimateChanged(before, estimated_minutes),
                ),
            ),
        )

    def change_segment_work_type(
        self, segment_id: UUID, work_type_id: UUID | None
    ) -> MutationResult[TaskAggregate]:
        self._ensure_structure_mutable()
        segment = self._segment(segment_id)
        if segment.work_type_id == work_type_id:
            return MutationResult(self)
        before = segment.work_type_id
        updated_segment = replace(segment, work_type_id=work_type_id)
        aggregate = self._replace_segment(updated_segment)
        return MutationResult(
            aggregate,
            (
                self._segment_fact(
                    updated_segment,
                    DomainFactType.SEGMENT_WORK_TYPE_CHANGED,
                    FactRole.DIRECT,
                    WorkTypeChanged(before, work_type_id),
                ),
            ),
        )

    def _progress_parent_if_needed(
        self,
    ) -> tuple[TaskAggregate, tuple[DomainFact, ...]]:
        if self.task.status is not TaskStatus.TODO:
            return self, ()
        updated_task = replace(self.task, status=TaskStatus.IN_PROGRESS)
        aggregate = TaskAggregate(updated_task, self.segments)
        fact = DomainFact(
            event_type=DomainFactType.TASK_STARTED,
            entity_type=DomainEntityType.TASK,
            entity_id=self.task.id,
            task_id=self.task.id,
            role=FactRole.PROPAGATED,
            payload=TaskStatusChanged(
                TaskStatus.TODO, TaskStatus.IN_PROGRESS
            ),
        )
        return aggregate, (fact,)

    def effective_estimate(self) -> EffectiveEstimate:
        active_segments = [
            segment for segment in self.segments if segment.status in _SEGMENT_OPEN
        ]
        if not active_segments:
            estimate = self.task.estimated_minutes
            return EffectiveEstimate(
                source=EstimateSource.TASK,
                known_subtotal_minutes=estimate or 0,
                unestimated_units=1 if estimate is None else 0,
                total_minutes=estimate,
                incomplete=estimate is None,
            )

        known = sum(
            segment.estimated_minutes or 0
            for segment in active_segments
            if segment.estimated_minutes is not None
        )
        unknown = sum(
            segment.estimated_minutes is None for segment in active_segments
        )
        return EffectiveEstimate(
            source=EstimateSource.SEGMENTS,
            known_subtotal_minutes=known,
            unestimated_units=unknown,
            total_minutes=None if unknown else known,
            incomplete=unknown > 0,
        )

    def next_action(self) -> NextAction | None:
        if self.task.status is TaskStatus.INBOX:
            return NextAction(
                NextActionType.CLARIFY_TASK,
                self.task.id,
                self.task.title,
            )
        if self.task.status in _TASK_TERMINAL:
            return None
        if not self.segments:
            return NextAction(
                NextActionType.WORK_ON_TASK,
                self.task.id,
                self.task.title,
            )

        ordered = self._ordered()
        for segment in ordered:
            if segment.status is SegmentStatus.IN_PROGRESS:
                return NextAction(
                    NextActionType.WORK_ON_SEGMENT,
                    segment.id,
                    segment.title,
                )
        for segment in ordered:
            if segment.status is SegmentStatus.TODO:
                return NextAction(
                    NextActionType.WORK_ON_SEGMENT,
                    segment.id,
                    segment.title,
                )
        return NextAction(
            NextActionType.REVIEW_COMPLETION,
            self.task.id,
            self.task.title,
        )

    def ready_for_completion(self) -> bool:
        return (
            self.task.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
            and bool(self.segments)
            and all(
                segment.status in _SEGMENT_TERMINAL for segment in self.segments
            )
        )

    def effective_task_work_type(self) -> EffectiveWorkType:
        if self.task.work_type_id is None:
            return EffectiveWorkType(None, WorkTypeOrigin.UNCLASSIFIED)
        return EffectiveWorkType(
            self.task.work_type_id, WorkTypeOrigin.TASK_INHERITED
        )

    def effective_segment_work_type(
        self, segment_id: UUID
    ) -> EffectiveWorkType:
        segment = self._segment(segment_id)
        if segment.work_type_id is not None:
            return EffectiveWorkType(
                segment.work_type_id,
                WorkTypeOrigin.SEGMENT_OVERRIDE,
            )
        if self.task.work_type_id is not None:
            return EffectiveWorkType(
                self.task.work_type_id,
                WorkTypeOrigin.TASK_INHERITED,
            )
        return EffectiveWorkType(None, WorkTypeOrigin.UNCLASSIFIED)

    def effective_segment_protection(
        self, segment_id: UUID
    ) -> ProtectionLevel:
        self._segment(segment_id)
        return self.task.protection

    def _task_fact(self, event_type, role, payload) -> DomainFact:
        return DomainFact(
            event_type=event_type,
            entity_type=DomainEntityType.TASK,
            entity_id=self.task.id,
            task_id=self.task.id,
            role=role,
            payload=payload,
        )

    def _segment_fact(self, segment, event_type, role, payload) -> DomainFact:
        return DomainFact(
            event_type=event_type,
            entity_type=DomainEntityType.SEGMENT,
            entity_id=segment.id,
            task_id=self.task.id,
            role=role,
            payload=payload,
        )
