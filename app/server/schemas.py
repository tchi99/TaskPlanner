from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.domain import ProtectionLevel, Task, TaskStatus


class TaskCaptureRequest(BaseModel):
    title: str
    notes: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = None

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
