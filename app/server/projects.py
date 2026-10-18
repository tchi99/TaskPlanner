from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.application.projects import (
    create_project, create_work_type, rename_work_type, get_project,
    list_project_tasks, list_projects, list_work_types,
)
from app.application.uow import UnitOfWork
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.recurring_availability import _owner
from app.server.schemas import (
    ProjectCreateRequest, ProjectResponse, TaskResponse,
    WorkTypeCreateRequest, WorkTypeUpdateRequest, WorkTypeResponse,
)

projects_router = APIRouter(prefix="/api/projects", tags=["projects"])
work_types_router = APIRouter(prefix="/api/work-types", tags=["work-types"])


@projects_router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create(payload: ProjectCreateRequest, uow: UnitOfWork = Depends(get_uow)) -> ProjectResponse:
    return ProjectResponse.from_domain(
        invoke(lambda: create_project(uow, payload.title, payload.description))
    )


@projects_router.get("", response_model=list[ProjectResponse])
def projects(uow: UnitOfWork = Depends(get_uow)) -> list[ProjectResponse]:
    return [ProjectResponse.from_domain(item) for item in list_projects(uow)]


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def detail(project_id: UUID, uow: UnitOfWork = Depends(get_uow)) -> ProjectResponse:
    return ProjectResponse.from_domain(invoke(lambda: get_project(uow, project_id)))


@projects_router.get("/{project_id}/tasks", response_model=list[TaskResponse])
def project_tasks(project_id: UUID, uow: UnitOfWork = Depends(get_uow)) -> list[TaskResponse]:
    return [TaskResponse.from_domain(item) for item in
            invoke(lambda: list_project_tasks(uow, project_id))]


@work_types_router.post("", response_model=WorkTypeResponse, status_code=status.HTTP_201_CREATED)
def create_type(request: Request, payload: WorkTypeCreateRequest,
                uow: UnitOfWork = Depends(get_uow)) -> WorkTypeResponse:
    return WorkTypeResponse.from_domain(invoke(lambda: create_work_type(
        uow, payload.name, payload.description, payload.scope_id, _owner(request))))


@work_types_router.patch("/{work_type_id}", response_model=WorkTypeResponse)
def update_type(work_type_id: UUID, request: Request, payload: WorkTypeUpdateRequest,
                uow: UnitOfWork = Depends(get_uow)) -> WorkTypeResponse:
    return WorkTypeResponse.from_domain(invoke(lambda: rename_work_type(
        uow, _owner(request), work_type_id, payload.name, payload.description,
        payload.expected_version)))


@work_types_router.get("", response_model=list[WorkTypeResponse])
def types(request: Request, uow: UnitOfWork = Depends(get_uow)) -> list[WorkTypeResponse]:
    return [WorkTypeResponse.from_domain(item) for item in
            list_work_types(uow, _owner(request))]
