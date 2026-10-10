from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Sequence
from uuid import UUID

from app.application.history import HistorySource, build_history_events
from app.application.uow import UnitOfWork
from app.domain import ProjectStatus, Task, TaskAggregate, TaskStatus


@dataclass(frozen=True, slots=True)
class ClarifyTaskCommand:
    task_id: UUID
    changed_fields: frozenset[str] = frozenset()
    title: str | None = None
    notes: str | None = None
    project_id: UUID | None = None
    work_type_id: UUID | None = None
    estimated_minutes: int | None = None
    due_at: datetime | None = None


def _require_active_project(uow: UnitOfWork, project_id: UUID | None) -> None:
    if project_id is None:
        return
    project = uow.projects.get(project_id)
    if project is None:
        raise ValueError("project does not exist")
    if project.status is not ProjectStatus.ACTIVE:
        raise ValueError("task requires an active project")


def _require_work_type(uow: UnitOfWork, work_type_id: UUID | None) -> None:
    if work_type_id is not None and uow.work_types.get(work_type_id) is None:
        raise ValueError("work type does not exist")


def clarify_task(uow: UnitOfWork, command: ClarifyTaskCommand) -> Task:
    allowed = {
        "title", "notes", "project_id", "work_type_id",
        "estimated_minutes", "due_at",
    }
    if not command.changed_fields <= allowed:
        raise ValueError("unsupported clarification field")

    with uow:
        aggregate = uow.tasks.get_aggregate(command.task_id)
        if aggregate is None:
            raise LookupError("task not found")
        if aggregate.task.status is not TaskStatus.INBOX:
            raise ValueError("only inbox tasks can be clarified")

        if "project_id" in command.changed_fields:
            _require_active_project(uow, command.project_id)
        if "work_type_id" in command.changed_fields:
            _require_work_type(uow, command.work_type_id)

        details = {
            field: getattr(command, field)
            for field in ("title", "notes", "project_id", "due_at")
            if field in command.changed_fields
        }
        task = replace(aggregate.task, **details)
        clarified = TaskAggregate(task, aggregate.segments).clarify()
        aggregate = clarified.value
        facts = list(clarified.facts)

        if "estimated_minutes" in command.changed_fields:
            estimate = aggregate.change_task_estimate(command.estimated_minutes)
            aggregate = estimate.value
            facts.extend(estimate.facts)
        if "work_type_id" in command.changed_fields:
            work_type = aggregate.change_task_work_type(command.work_type_id)
            aggregate = work_type.value
            facts.extend(work_type.facts)

        uow.tasks.save(aggregate.task)
        uow.history.append_many(build_history_events(facts, direct_source=HistorySource.USER))
        uow.commit()
        return aggregate.task


def assign_task_project(
    uow: UnitOfWork, task_id: UUID, project_id: UUID | None
) -> Task:
    # Assignment and detachment are explicit operations, not clarification.
    with uow:
        task = uow.tasks.get(task_id)
        if task is None:
            raise LookupError("task not found")
        if task.project_id == project_id:
            return task
        _require_active_project(uow, project_id)
        updated = replace(task, project_id=project_id)
        uow.tasks.save(updated)
        uow.commit()
        return updated


def list_tasks(uow: UnitOfWork) -> Sequence[Task]:
    with uow:
        return tuple(uow.tasks.list_all())


def get_task(uow: UnitOfWork, task_id: UUID) -> Task:
    with uow:
        task = uow.tasks.get(task_id)
        if task is None:
            raise LookupError("task not found")
        return task
