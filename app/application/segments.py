from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.application.history import HistorySource, build_history_events
from app.application.uow import UnitOfWork
from app.domain import MutationResult, ProtectionLevel, TaskAggregate


@dataclass(frozen=True, slots=True)
class EditSegmentCommand:
    task_id: UUID
    segment_id: UUID
    changed_fields: frozenset[str] = frozenset()
    title: str | None = None
    estimated_minutes: int | None = None
    work_type_id: UUID | None = None
    protection_override: ProtectionLevel | None = None
    confirm_protection_downgrade: bool = False


def get_task_aggregate(uow: UnitOfWork, task_id: UUID) -> TaskAggregate:
    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        return aggregate


Change = Callable[[TaskAggregate, UnitOfWork], MutationResult[TaskAggregate]]


def _mutate(uow: UnitOfWork, task_id: UUID, change: Change) -> TaskAggregate:
    with uow:
        aggregate = uow.tasks.get_aggregate(task_id)
        if aggregate is None:
            raise LookupError("task not found")
        result = change(aggregate, uow)
        if result.value != aggregate or result.facts:
            uow.tasks.save_aggregate(result.value)
            uow.history.append_many(
                build_history_events(result.facts, direct_source=HistorySource.USER)
            )
            uow.commit()
        return result.value


def _validate_work_type(uow: UnitOfWork, work_type_id: UUID | None) -> None:
    if work_type_id is not None and uow.work_types.get(work_type_id) is None:
        raise ValueError("work type does not exist")


def add_segment(
    uow: UnitOfWork, task_id: UUID, title: str,
    estimated_minutes: int | None = None, work_type_id: UUID | None = None,
    protection_override: ProtectionLevel | None = None,
) -> TaskAggregate:
    def change(aggregate: TaskAggregate, active: UnitOfWork):
        _validate_work_type(active, work_type_id)
        return aggregate.add_segment(
            title.strip(), estimated_minutes=estimated_minutes,
            work_type_id=work_type_id, protection_override=protection_override,
        )
    return _mutate(uow, task_id, change)


def edit_segment(uow: UnitOfWork, command: EditSegmentCommand) -> TaskAggregate:
    if not command.changed_fields <= {
        "title", "estimated_minutes", "work_type_id", "protection_override",
        "confirm_protection_downgrade"
    }:
        raise ValueError("unsupported segment field")

    def change(aggregate: TaskAggregate, active: UnitOfWork):
        facts = []
        if "title" in command.changed_fields:
            if command.title is None:
                raise ValueError("title cannot be null")
            result = aggregate.rename_segment(command.segment_id, command.title)
            aggregate = result.value
            facts.extend(result.facts)
        if "estimated_minutes" in command.changed_fields:
            result = aggregate.change_segment_estimate(
                command.segment_id, command.estimated_minutes
            )
            aggregate = result.value
            facts.extend(result.facts)
        if "work_type_id" in command.changed_fields:
            _validate_work_type(active, command.work_type_id)
            result = aggregate.change_segment_work_type(
                command.segment_id, command.work_type_id
            )
            aggregate = result.value
            facts.extend(result.facts)
        if "protection_override" in command.changed_fields:
            before = aggregate.effective_segment_protection(command.segment_id)
            result = aggregate.change_segment_protection(
                command.segment_id, command.protection_override
            )
            after = result.value.effective_segment_protection(command.segment_id)
            rank = {
                ProtectionLevel.FLEXIBLE: 0,
                ProtectionLevel.REPLANNABLE: 1,
                ProtectionLevel.PROTECTED: 2,
            }
            if rank[after] < rank[before] and not command.confirm_protection_downgrade:
                raise ValueError("lowering segment protection requires explicit confirmation")
            aggregate = result.value
            facts.extend(result.facts)
        return MutationResult(aggregate, tuple(facts))

    return _mutate(uow, command.task_id, change)


def reorder_segments(
    uow: UnitOfWork, task_id: UUID, ordered_ids: Sequence[UUID]
) -> TaskAggregate:
    return _mutate(
        uow, task_id,
        lambda aggregate, _: aggregate.reorder_segments(ordered_ids),
    )


def transition_segment(
    uow: UnitOfWork, task_id: UUID, segment_id: UUID, action: str
) -> TaskAggregate:
    commands = {
        "start": TaskAggregate.start_segment,
        "complete": TaskAggregate.complete_segment,
        "cancel": TaskAggregate.cancel_segment,
    }
    if action not in commands:
        raise ValueError("unsupported segment transition")
    return _mutate(
        uow, task_id, lambda aggregate, _: commands[action](aggregate, segment_id)
    )


def remove_segment(uow: UnitOfWork, task_id: UUID, segment_id: UUID) -> TaskAggregate:
    return _mutate(
        uow, task_id, lambda aggregate, _: aggregate.remove_segment(segment_id)
    )


def transition_task(uow: UnitOfWork, task_id: UUID, action: str) -> TaskAggregate:
    commands = {
        "start": TaskAggregate.start,
        "complete": TaskAggregate.complete,
        "cancel": TaskAggregate.cancel,
        "reopen": TaskAggregate.reopen,
    }
    if action not in commands:
        raise ValueError("unsupported task transition")
    return _mutate(
        uow, task_id, lambda aggregate, _: commands[action](aggregate)
    )


def change_task_protection(
    uow: UnitOfWork, task_id: UUID, protection: ProtectionLevel,
    confirm_downgrade: bool = False,
) -> TaskAggregate:
    def change(aggregate: TaskAggregate, _: UnitOfWork):
        rank = {
            ProtectionLevel.FLEXIBLE: 0,
            ProtectionLevel.REPLANNABLE: 1,
            ProtectionLevel.PROTECTED: 2,
        }
        if rank[protection] < rank[aggregate.task.protection] and not confirm_downgrade:
            raise ValueError("lowering task protection requires explicit confirmation")
        return aggregate.change_task_protection(protection)
    return _mutate(uow, task_id, change)
