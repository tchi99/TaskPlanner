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


def create_work_type(uow: UnitOfWork, name: str, description: str | None = None) -> WorkType:
    work_type = WorkType(name=name, description=description)
    with uow:
        uow.work_types.add(work_type)
        uow.commit()
    return work_type


def list_work_types(uow: UnitOfWork) -> Sequence[WorkType]:
    with uow:
        return tuple(uow.work_types.list_all())
