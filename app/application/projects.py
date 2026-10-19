from __future__ import annotations

from typing import Sequence
from uuid import UUID

from app.application.uow import UnitOfWork
from app.domain import Project, Task, WorkType


def create_project(uow: UnitOfWork, title: str, description: str | None = None) -> Project:
    project = Project(title=title, description=description)
    with uow:
        uow.projects.add(project)
        uow.commit()
    return project


def list_projects(uow: UnitOfWork) -> Sequence[Project]:
    with uow:
        return tuple(uow.projects.list_all())


def get_project(uow: UnitOfWork, project_id: UUID) -> Project:
    with uow:
        project = uow.projects.get(project_id)
        if project is None:
            raise LookupError("project not found")
        return project


def list_project_tasks(uow: UnitOfWork, project_id: UUID) -> Sequence[Task]:
    with uow:
        if uow.projects.get(project_id) is None:
            raise LookupError("project not found")
        return tuple(uow.tasks.list_by_project(project_id))


def create_work_type(uow: UnitOfWork, name: str, description: str | None,
                     scope_id: UUID, owner: str) -> WorkType:
    with uow:
        uow.lock_planning()
        scope = uow.schedule_scopes.get(owner, scope_id)
        if scope is None or scope.state != "ACTIVE":
            raise ValueError("active parent scope must belong to the current user")
        work_type = WorkType(name=name, description=description, scope_id=scope_id)
        uow.work_types.add(work_type)
        uow.schedule_scopes.audit(owner, "WORK_TYPE_CREATED", {
            "work_type_id": str(work_type.id), "scope_id": str(scope_id)}, None)
        uow.commit()
        return work_type


def rename_work_type(uow: UnitOfWork, owner: str, work_type_id: UUID,
                     name: str, description: str | None,
                     expected_version: int) -> WorkType:
    with uow:
        uow.lock_planning()
        old = uow.work_types.get(work_type_id)
        if old is None or uow.schedule_scopes.get(owner, old.scope_id) is None:
            raise LookupError("work type not found for owner")
        from app.domain.recurring_availability import RuleConflict
        if old.version != expected_version:
            raise RuleConflict("work type version changed")
        if not name.strip():
            raise ValueError("work type name cannot be blank")
        changed = uow.work_types.rename(work_type_id, expected_version,
                                        name.strip(), description)
        uow.schedule_scopes.audit(owner, "WORK_TYPE_UPDATED", {
            "work_type_id": str(work_type_id), "scope_id": str(old.scope_id),
            "before_version": old.version, "after_version": changed.version}, None)
        uow.commit()
        return changed


def list_work_types(uow: UnitOfWork, owner: str) -> Sequence[WorkType]:
    with uow:
        return tuple(uow.work_types.list_owner(owner))
