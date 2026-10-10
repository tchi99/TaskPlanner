from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain import Project, ProjectStatus, ProtectionLevel, Task, TaskAggregate, TaskStatus, WorkType


class TaskCaptureRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone")
        return value


class TaskResponse(BaseModel):
    id: UUID
    title: str
    notes: str | None
    status: TaskStatus
    protection: ProtectionLevel
    estimated_minutes: int | None
    due_at: datetime | None
    created_at: datetime
    project_id: UUID | None
    work_type_id: UUID | None

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            title=task.title,
            notes=task.notes,
            status=task.status,
            protection=task.protection,
            estimated_minutes=task.estimated_minutes,
            due_at=task.due_at,
            created_at=task.created_at,
            project_id=task.project_id,
            work_type_id=task.work_type_id,
        )


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: ProjectStatus

    @classmethod
    def from_domain(cls, project: Project) -> "ProjectResponse":
        return cls(id=project.id, title=project.title,
                   description=project.description, status=project.status)


class WorkTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class WorkTypeResponse(BaseModel):
    id: UUID
    name: str
    description: str | None

    @classmethod
    def from_domain(cls, value: WorkType) -> "WorkTypeResponse":
        return cls(id=value.id, name=value.name, description=value.description)


class TaskClarificationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = None
    project_id: UUID | None = None
    work_type_id: UUID | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value.strip() if value is not None else None

    @field_validator("due_at")
    @classmethod
    def aware_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone")
        return value


class TaskProtectionRequest(BaseModel):
    protection: ProtectionLevel
    confirm_downgrade: bool = False


class TaskProjectRequest(BaseModel):
    project_id: UUID | None


class SegmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    estimated_minutes: int | None = Field(default=None, gt=0)
    work_type_id: UUID | None = None
    protection_override: ProtectionLevel | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class SegmentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    estimated_minutes: int | None = Field(default=None, gt=0)
    work_type_id: UUID | None = None
    protection_override: ProtectionLevel | None = None
    confirm_protection_downgrade: bool = False

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value.strip() if value is not None else None


class SegmentReorderRequest(BaseModel):
    segment_ids: list[UUID]


class NextActionResponse(BaseModel):
    action_type: str
    target_id: UUID
    label: str


class EstimateResponse(BaseModel):
    source: str
    known_subtotal_minutes: int
    unestimated_units: int
    total_minutes: int | None
    incomplete: bool


class ProgressResponse(BaseModel):
    total_segments: int
    completed_segments: int
    cancelled_segments: int
    open_segments: int
    completion_percent: float | None


class SegmentResponse(BaseModel):
    id: UUID
    task_id: UUID
    title: str
    position: int
    status: str
    estimated_minutes: int | None
    work_type_id: UUID | None
    effective_work_type_id: UUID | None
    work_type_origin: str
    effective_protection: str
    protection_override: ProtectionLevel | None
    allowed_actions: list[str]


class TaskDetailResponse(TaskResponse):
    effective_work_type_id: UUID | None
    work_type_origin: str
    segments: list[SegmentResponse]
    next_action: NextActionResponse | None
    effective_estimate: EstimateResponse
    progress: ProgressResponse
    ready_for_completion: bool
    allowed_actions: list[str]

    @classmethod
    def from_aggregate(cls, aggregate: "TaskAggregate") -> "TaskDetailResponse":
        task = aggregate.task
        structural = task.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
        ordered = sorted(aggregate.segments, key=lambda segment: segment.position)
        entries = []
        for segment in ordered:
            work_type = aggregate.effective_segment_work_type(segment.id)
            actions = []
            if structural:
                actions.append("EDIT")
                if segment.status.value == "TODO":
                    actions.extend(["START", "COMPLETE", "CANCEL", "REMOVE"])
                elif segment.status.value == "IN_PROGRESS":
                    actions.extend(["COMPLETE", "CANCEL"])
            entries.append(SegmentResponse(
                id=segment.id, task_id=segment.task_id, title=segment.title,
                position=segment.position, status=segment.status.value,
                estimated_minutes=segment.estimated_minutes,
                work_type_id=segment.work_type_id,
                effective_work_type_id=work_type.work_type_id,
                work_type_origin=work_type.origin.value,
                effective_protection=aggregate.effective_segment_protection(segment.id).value,
                protection_override=segment.protection_override,
                allowed_actions=actions,
            ))
        action = aggregate.next_action()
        estimate = aggregate.effective_estimate()
        completed = sum(s.status.value == "DONE" for s in ordered)
        cancelled = sum(s.status.value == "CANCELLED" for s in ordered)
        total = len(ordered)
        task_actions = []
        if structural:
            task_actions.extend(["ADD_SEGMENT", "REORDER_SEGMENTS", "CANCEL_TASK"])
            if task.status is TaskStatus.TODO and not total:
                task_actions.append("START_TASK")
            if not any(s.status.value in {"TODO", "IN_PROGRESS"} for s in ordered):
                task_actions.append("COMPLETE_TASK")
        elif task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            task_actions.append("REOPEN_TASK")
        return cls(
            **TaskResponse.from_domain(task).model_dump(),
            effective_work_type_id=aggregate.effective_task_work_type().work_type_id,
            work_type_origin=aggregate.effective_task_work_type().origin.value,
            segments=entries,
            next_action=(NextActionResponse(
                action_type=action.action_type.value,
                target_id=action.target_id, label=action.label,
            ) if action else None),
            effective_estimate=EstimateResponse(
                source=estimate.source.value,
                known_subtotal_minutes=estimate.known_subtotal_minutes,
                unestimated_units=estimate.unestimated_units,
                total_minutes=estimate.total_minutes,
                incomplete=estimate.incomplete,
            ),
            progress=ProgressResponse(
                total_segments=total,
                completed_segments=completed,
                cancelled_segments=cancelled,
                open_segments=total - completed - cancelled,
                completion_percent=(100 * completed / total if total else None),
            ),
            ready_for_completion=aggregate.ready_for_completion(),
            allowed_actions=task_actions,
        )
