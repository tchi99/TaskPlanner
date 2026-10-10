from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.application.segments import (
    EditSegmentCommand, add_segment, edit_segment, get_task_aggregate,
    remove_segment, reorder_segments, transition_segment, transition_task,
)
from app.application.uow import UnitOfWork
from app.infrastructure.uow import get_uow
from app.server.errors import invoke
from app.server.schemas import (
    SegmentCreateRequest, SegmentReorderRequest, SegmentUpdateRequest,
    TaskDetailResponse,
)

router = APIRouter(prefix="/api/tasks", tags=["segments"])


@router.get("/{task_id}/detail", response_model=TaskDetailResponse)
def detail(task_id: UUID, uow: UnitOfWork = Depends(get_uow)) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(
        invoke(lambda: get_task_aggregate(uow, task_id))
    )


@router.post(
    "/{task_id}/segments",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create(
    task_id: UUID, payload: SegmentCreateRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(invoke(lambda: add_segment(
        uow, task_id, payload.title, payload.estimated_minutes, payload.work_type_id
    )))


@router.put("/{task_id}/segments/order", response_model=TaskDetailResponse)
def reorder(
    task_id: UUID, payload: SegmentReorderRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(invoke(lambda: reorder_segments(
        uow, task_id, payload.segment_ids
    )))


@router.patch("/{task_id}/segments/{segment_id}", response_model=TaskDetailResponse)
def update(
    task_id: UUID, segment_id: UUID, payload: SegmentUpdateRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(invoke(lambda: edit_segment(
        uow, EditSegmentCommand(
            task_id=task_id, segment_id=segment_id,
            changed_fields=frozenset(payload.model_fields_set),
            **payload.model_dump(exclude_unset=True),
        )
    )))


@router.delete("/{task_id}/segments/{segment_id}", response_model=TaskDetailResponse)
def remove(
    task_id: UUID, segment_id: UUID, uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(
        invoke(lambda: remove_segment(uow, task_id, segment_id))
    )


@router.post(
    "/{task_id}/segments/{segment_id}/{action}", response_model=TaskDetailResponse
)
def move_segment(
    task_id: UUID, segment_id: UUID,
    action: Literal["start", "complete", "cancel"],
    uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(
        invoke(lambda: transition_segment(uow, task_id, segment_id, action))
    )


@router.post("/{task_id}/transition/{action}", response_model=TaskDetailResponse)
def move_task(
    task_id: UUID, action: Literal["start", "complete", "cancel", "reopen"],
    uow: UnitOfWork = Depends(get_uow),
) -> TaskDetailResponse:
    return TaskDetailResponse.from_aggregate(
        invoke(lambda: transition_task(uow, task_id, action))
    )
