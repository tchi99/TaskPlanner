from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain import ProtectionLevel, Task, TaskStatus


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
        )
