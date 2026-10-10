from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain import Project, ProjectStatus, ProtectionLevel, Task, TaskStatus, WorkType


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


class TaskProjectRequest(BaseModel):
    project_id: UUID | None
