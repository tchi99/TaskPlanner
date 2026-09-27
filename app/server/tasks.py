from fastapi import APIRouter, Depends, status

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
