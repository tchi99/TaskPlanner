from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.infrastructure.db import Base


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("persisted datetimes must be timezone-aware")
        normalized = value.astimezone(timezone.utc)
        if dialect.name == "sqlite":
            return normalized.replace(tzinfo=None)
        return normalized

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            # SQLite's DateTime storage has no timezone field. New writes are
            # normalized to UTC before bind; legacy naive values are preserved
            # without inventing an offset that was never stored.
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ProjectRecord(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','ARCHIVED')",
            name="ck_projects_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class WorkTypeRecord(Base):
    __tablename__ = "work_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_created_at", "status", "created_at"),
        CheckConstraint(
            "status IN ('INBOX','TODO','IN_PROGRESS','DONE','CANCELLED')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "protection IN ('PROTECTED','REPLANNABLE','FLEXIBLE')",
            name="ck_tasks_protection",
        ),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes > 0",
            name="ck_tasks_estimated_minutes",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    protection: Mapped[str] = mapped_column(String(32), nullable=False)
    work_type_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("work_types.id", ondelete="RESTRICT"),
        nullable=True,
    )
    estimated_minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TaskSegmentRecord(Base):
    __tablename__ = "task_segments"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "position",
            name="uq_task_segments_task_position",
        ),
        CheckConstraint(
            "status IN ('TODO','IN_PROGRESS','DONE','CANCELLED')",
            name="ck_task_segments_status",
        ),
        CheckConstraint("position >= 0", name="ck_task_segments_position"),
        CheckConstraint(
            "protection_override IS NULL OR protection_override IN ('PROTECTED','REPLANNABLE','FLEXIBLE')",
            name="ck_task_segments_protection_override",
        ),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes > 0",
            name="ck_task_segments_estimated_minutes",
        ),
        Index("ix_task_segments_task_position", "task_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer(), nullable=False)
    work_type_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("work_types.id", ondelete="RESTRICT"),
        nullable=True,
    )
    estimated_minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    protection_override: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AvailabilityBlockRecord(Base):
    __tablename__ = "availability_blocks"
    __table_args__ = (Index("ix_availability_blocks_week", "week_start"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date(), nullable=False)
    starts_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ends_at: Mapped[str] = mapped_column(String(40), nullable=False)
    work_type_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("work_types.id", ondelete="RESTRICT"),
        nullable=True,
    )


class ConfirmedTimeBlockRecord(Base):
    """Explicitly accepted local reservations, never events in Google Calendar."""
    __tablename__ = "confirmed_time_blocks"
    __table_args__ = (
        Index("ix_confirmed_time_blocks_week", "week_start"),
        UniqueConstraint("task_id", "segment_id", "starts_at",
                         name="uq_confirmed_time_block_unit_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date(), nullable=False)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False,
    )
    segment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("task_segments.id", ondelete="RESTRICT"), nullable=True,
    )
    work_type_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True,
    )
    starts_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ends_at: Mapped[str] = mapped_column(String(40), nullable=False)


class DailyReviewRecord(Base):
    """Daily choices only, not a task or calendar mutation."""
    __tablename__ = "daily_reviews"
    __table_args__ = (
        Index("ix_daily_reviews_timezone_day", "timezone_name", "day"),
        CheckConstraint("state IN ('OPEN','CLOSED')", name="ck_daily_reviews_state"),
        CheckConstraint("revision > 0", name="ck_daily_reviews_revision"),
    )

    day: Mapped[date] = mapped_column(Date(), primary_key=True)
    timezone_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    selected_task_ids: Mapped[list[str]] = mapped_column(JSON(), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    followups: Mapped[list[dict[str, str]]] = mapped_column(JSON(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer(), nullable=False)


class WeeklyDecisionRecord(Base):
    """Confirmed review choice; never the operative task state."""
    __tablename__ = "weekly_decisions"
    __table_args__ = (
        CheckConstraint("subject_kind IN ('TASK','PROJECT')",
                        name="ck_weekly_decisions_subject"),
        CheckConstraint(
            "action IN ('RECIRCULATE','POSTPONE','REVIEW_LATER','DELEGATE','ABANDON')",
            name="ck_weekly_decisions_action",
        ),
        CheckConstraint("revision > 0", name="ck_weekly_decisions_revision"),
    )

    week_start: Mapped[date] = mapped_column(Date(), primary_key=True)
    timezone_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    review_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer(), nullable=False)


class HistoryEventRecord(Base):
    __tablename__ = "history_events"
    __table_args__ = (
        Index("ix_history_events_task_sequence", "task_id", "sequence"),
        Index(
            "ix_history_events_entity_sequence",
            "entity_type",
            "entity_id",
            "sequence",
        ),
        Index(
            "ix_history_events_correlation_sequence",
            "correlation_id",
            "sequence",
        ),
        CheckConstraint(
            "entity_type IN ('TASK','SEGMENT')",
            name="ck_history_events_entity_type",
        ),
        CheckConstraint(
            "source IN ('USER','SYSTEM_RULE','IMPORT','AI')",
            name="ck_history_events_source",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_history_events_schema_version",
        ),
        {"sqlite_autoincrement": True},
    )

    sequence: Mapped[int] = mapped_column(
        Integer(),
        primary_key=True,
        autoincrement=True,
    )
    id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, object | None]] = mapped_column(JSON(), nullable=False)


class ResumePointRecord(Base):
    """Explicit resume note; not an observed fact or a work session."""
    __tablename__ = "resume_points"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_resume_points_revision"),
        CheckConstraint(
            "action_type IN ('CLARIFY_TASK','WORK_ON_TASK','WORK_ON_SEGMENT','REVIEW_COMPLETION')",
            name="ck_resume_points_action_type",
        ),
        CheckConstraint("text IS NULL OR length(text) BETWEEN 1 AND 240",
                        name="ck_resume_points_text_length"),
    )

    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), primary_key=True,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    revision: Mapped[int] = mapped_column(Integer(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
