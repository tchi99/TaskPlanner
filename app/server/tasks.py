from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.application.clarification import (
    ClarifyTaskCommand, assign_task_project, clarify_task, get_task, list_tasks,
)
from app.server.errors import invoke
from app.server.schemas import TaskClarificationRequest, TaskProjectRequest, TaskProtectionRequest
from app.application.tasks import CaptureTaskCommand, capture_task, list_inbox
from app.application.uow import UnitOfWork
from app.infrastructure.uow import get_uow
from app.server.schemas import TaskCaptureRequest, TaskResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def capture(
    payload: TaskCaptureRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskResponse:
    task = capture_task(
        uow,
        CaptureTaskCommand(
            title=payload.title,
            notes=payload.notes,
            due_at=payload.due_at,
            estimated_minutes=payload.estimated_minutes,
        ),
    )
    return TaskResponse.from_domain(task)


@router.get("/inbox", response_model=list[TaskResponse])
def inbox(uow: UnitOfWork = Depends(get_uow)) -> list[TaskResponse]:
    return [TaskResponse.from_domain(task) for task in list_inbox(uow)]


@router.get("", response_model=list[TaskResponse])
def all_tasks(uow: UnitOfWork = Depends(get_uow)) -> list[TaskResponse]:
    return [TaskResponse.from_domain(task) for task in list_tasks(uow)]


@router.get("/{task_id}", response_model=TaskResponse)
def task_detail(task_id: UUID, uow: UnitOfWork = Depends(get_uow)) -> TaskResponse:
    return TaskResponse.from_domain(invoke(lambda: get_task(uow, task_id)))


@router.post("/{task_id}/clarify", response_model=TaskResponse)
def clarify(
    task_id: UUID,
    payload: TaskClarificationRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskResponse:
    return TaskResponse.from_domain(
        invoke(lambda: clarify_task(
            uow,
            ClarifyTaskCommand(
                task_id=task_id,
                changed_fields=frozenset(payload.model_fields_set),
                **payload.model_dump(exclude_unset=True),
            ),
        ))
    )


@router.patch("/{task_id}/protection", response_model=TaskResponse)
def protect_task(
    task_id: UUID, payload: TaskProtectionRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskResponse:
    from app.application.segments import change_task_protection
    return TaskResponse.from_domain(invoke(
        lambda: change_task_protection(
            uow, task_id, payload.protection, payload.confirm_downgrade
        ).task
    ))


@router.patch("/{task_id}/project", response_model=TaskResponse)
def change_project(
    task_id: UUID,
    payload: TaskProjectRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskResponse:
    return TaskResponse.from_domain(
        invoke(lambda: assign_task_project(uow, task_id, payload.project_id))
    )
