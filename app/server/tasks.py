from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.application.tasks import CaptureTaskCommand, capture_task, list_inbox
from app.infrastructure.db import get_session
from app.infrastructure.task_repository import SqlTaskRepository
from app.server.schemas import TaskCaptureRequest, TaskResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def capture(
    payload: TaskCaptureRequest,
    session: Session = Depends(get_session),
) -> TaskResponse:
    repository = SqlTaskRepository(session)
    task = capture_task(
        repository,
        CaptureTaskCommand(
            title=payload.title,
            notes=payload.notes,
            due_at=payload.due_at,
            estimated_minutes=payload.estimated_minutes,
        ),
    )
    return TaskResponse.from_domain(task)


@router.get("/inbox", response_model=list[TaskResponse])
def inbox(session: Session = Depends(get_session)) -> list[TaskResponse]:
    repository = SqlTaskRepository(session)
    return [TaskResponse.from_domain(task) for task in list_inbox(repository)]
