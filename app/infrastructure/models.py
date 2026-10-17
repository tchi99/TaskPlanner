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
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.infrastructure.db import Base


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
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



class ScheduleScopeRecord(Base):
    """An owner-specific scheduling envelope, never a schedulable WorkType."""
    __tablename__ = "schedule_scopes"
    __table_args__ = (
        Index("ix_schedule_scopes_owner", "owner_id"),
        CheckConstraint("version > 0", name="ck_schedule_scope_version"),
        CheckConstraint("state IN ('ACTIVE','INACTIVE')", name="ck_schedule_scope_state"),
        UniqueConstraint("owner_id", "name", name="uq_schedule_scope_owner_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_compatibility: Mapped[bool] = mapped_column(nullable=False, default=False)


class WorkTypeScopeVersionRecord(Base):
    """CAS counter for one owner's temporal WorkType affiliation history."""
    __tablename__ = "work_type_scope_versions"
    owner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)


class WorkTypeScopeAssignmentRecord(Base):
    """Append-only, civil-dated attachment; later records never rewrite history."""
    __tablename__ = "work_type_scope_assignments"
    __table_args__ = (
        UniqueConstraint("owner_id", "work_type_id", "version",
                         name="uq_scope_assignment_version"),
        Index("ix_scope_assignment_lookup", "owner_id", "work_type_id",
              "effective_from", "version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=False,
    )
    scope_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ScopeChangeAuditRecord(Base):
    """Append-only correlated audit (no legacy history event constraint rewrite)."""
    __tablename__ = "scope_change_audit"
    __table_args__ = (Index("ix_scope_audit_owner", "owner_id", "recorded_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ScopeChangeCommandRecord(Base):
    __tablename__ = "scope_change_commands"
    owner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON(), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


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
    scope_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=True,
    )

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
        CheckConstraint("status IN ('CONFIRMED','CANCELLED','SUPERSEDED')",
                        name="ck_confirmed_time_blocks_status"),
        CheckConstraint("revision > 0", name="ck_confirmed_time_blocks_revision"),
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
    scope_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=True,
    )

    transferred_from_work_type_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CONFIRMED")
    revision: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)


class TimeBlockCommandRecord(Base):
    """TP-025B owner-scoped receipt committed with bookings and history."""
    __tablename__ = "time_block_confirmation_commands"
    __table_args__ = (Index("ix_time_block_command_owner", "owner_id"),)

    owner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


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
            "entity_type IN ('TASK','SEGMENT','AVAILABILITY_RULE','AVAILABILITY_EXCEPTION','TIME_BLOCK','ELIGIBILITY_SERIES')",
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


class WorkSessionRecord(Base):
    """Actual observed intervals, independent of task status and reserved time."""
    __tablename__ = "work_sessions"
    __table_args__ = (
        Index("ix_work_sessions_task_started", "task_id", "started_at"),
        Index("uq_work_sessions_single_active", "status", unique=True,
              sqlite_where=text("status = 'ACTIVE'"),
              postgresql_where=text("status = 'ACTIVE'")),
        CheckConstraint("status IN ('ACTIVE','PAUSED','FINISHED')",
                        name="ck_work_sessions_status"),
        CheckConstraint("active_seconds >= 0 AND interruptions >= 0 AND revision > 0",
                        name="ck_work_sessions_counters"),
        CheckConstraint("estimated_minutes IS NULL OR estimated_minutes > 0",
                        name="ck_work_sessions_estimate"),
        CheckConstraint("planned_minutes IS NULL OR planned_minutes > 0",
                        name="ck_work_sessions_plan"),
        CheckConstraint("(status = 'ACTIVE' AND active_since IS NOT NULL AND finished_at IS NULL) OR "
                        "(status = 'PAUSED' AND active_since IS NULL AND finished_at IS NULL) OR "
                        "(status = 'FINISHED' AND active_since IS NULL AND finished_at IS NOT NULL)",
                        name="ck_work_sessions_lifecycle"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False,
    )
    segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    active_since: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    active_seconds: Mapped[int] = mapped_column(Integer(), nullable=False)
    interruptions: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer(), nullable=False)
    work_type_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    planned_minutes: Mapped[int | None] = mapped_column(Integer(), nullable=True)


class EligibilitySeriesRecord(Base):
    """TP-025A: a dedicated opt-in permission, not a legacy capacity rule."""
    __tablename__ = "eligibility_series"
    __table_args__ = (
        Index("ix_eligibility_series_owner", "owner_id"),
        CheckConstraint("version > 0", name="ck_eligibility_series_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=False,
    )
    work_type_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class EligibilityRevisionRecord(Base):
    __tablename__ = "eligibility_revisions"
    __table_args__ = (
        UniqueConstraint("series_id", "number", name="uq_eligibility_revision_number"),
        Index("ix_eligibility_revision_dates", "series_id", "effective_from", "number"),
        CheckConstraint("number > 0", name="ck_eligibility_revision_number"),
        CheckConstraint("priority_rank IS NULL OR priority_rank > 0",
                        name="ck_eligibility_priority_rank"),
        CheckConstraint("start_fold IS NULL OR start_fold IN (0,1)",
                        name="ck_eligibility_start_fold"),
        CheckConstraint("end_fold IS NULL OR end_fold IN (0,1)",
                        name="ck_eligibility_end_fold"),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_from",
                        name="ck_eligibility_revision_range"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    series_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("eligibility_series.id", ondelete="RESTRICT"), nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date(), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    days_of_week: Mapped[list[int]] = mapped_column(JSON(), nullable=False)
    starts_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    ends_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    priority_rank: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    start_fold: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    end_fold: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    supersedes_future: Mapped[bool] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class EligibilityExceptionRecord(Base):
    """Stable target/version row; content revisions are never overwritten."""
    __tablename__ = "eligibility_exceptions"
    __table_args__ = (
        Index("ix_eligibility_exceptions_owner", "owner_id", "series_id"),
        UniqueConstraint("owner_id", "series_id", "original_local_date",
                         name="uq_eligibility_exception_target"),
        CheckConstraint("version > 0", name="ck_eligibility_exception_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    series_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("eligibility_series.id", ondelete="RESTRICT"), nullable=False,
    )
    original_local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class EligibilityExceptionRevisionRecord(Base):
    __tablename__ = "eligibility_exception_revisions"
    __table_args__ = (
        UniqueConstraint("exception_id", "number",
                         name="uq_eligibility_exception_revision"),
        CheckConstraint("number > 0", name="ck_eligibility_exception_rev_number"),
        CheckConstraint("action IN ('REMOVE','MOVE')",
                        name="ck_eligibility_exception_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    exception_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("eligibility_exceptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RecurringAvailabilityRuleRecord(Base):
    """Stable series identity; optimistic revision counter is CAS-updated."""
    __tablename__ = "recurring_availability_rules"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_recurring_rules_version"),
        Index("ix_recurring_rules_owner", "owner_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RecurringAvailabilityRevisionRecord(Base):
    """Immutable full configuration at a civil effective date."""
    __tablename__ = "recurring_availability_revisions"
    __table_args__ = (
        UniqueConstraint("rule_id", "number", name="uq_recurring_revision_number"),
        CheckConstraint("number > 0", name="ck_recurring_revisions_number"),
        CheckConstraint("kind IN ('GENERAL','CATEGORIZED')", name="ck_recurring_revisions_kind"),
        CheckConstraint("mode IS NULL OR mode IN ('PROTECTED','PREFERRED')",
                        name="ck_recurring_revisions_mode"),
        CheckConstraint("start_fold IS NULL OR start_fold IN (0,1)",
                        name="ck_recurring_revisions_start_fold"),
        CheckConstraint("end_fold IS NULL OR end_fold IN (0,1)",
                        name="ck_recurring_revisions_end_fold"),
        CheckConstraint("valid_until IS NULL OR valid_until > effective_from",
                        name="ck_recurring_revisions_range"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recurring_availability_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date(), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    days_of_week: Mapped[list[int]] = mapped_column(JSON(), nullable=False)
    starts_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    ends_at_local: Mapped[str] = mapped_column(String(5), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    work_type_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True,
    )
    scope_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=True,
    )

    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    start_fold: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    end_fold: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    supersedes_future: Mapped[bool] = mapped_column(nullable=False, default=False)


class AvailabilityExceptionRecord(Base):
    """Current exception snapshot; every mutation also appends a history event."""
    __tablename__ = "availability_exceptions"
    __table_args__ = (
        Index("ix_availability_exceptions_owner", "owner_id"),
        UniqueConstraint("owner_id", "rule_id", "original_local_date",
                         name="uq_availability_exception_target"),
        CheckConstraint("version > 0", name="ck_availability_exceptions_version"),
        CheckConstraint("action IN ('CANCEL','REPLACE','ADD','UNAVAILABLE')",
                        name="ck_availability_exceptions_action"),
        CheckConstraint("mode IS NULL OR mode IN ('PROTECTED','PREFERRED')",
                        name="ck_availability_exceptions_mode"),
        CheckConstraint("kind IS NULL OR kind IN ('GENERAL','CATEGORIZED')",
                        name="ck_availability_exceptions_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("recurring_availability_rules.id", ondelete="RESTRICT"),
        nullable=True,
    )
    original_local_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(String(40), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(String(40), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    work_type_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_types.id", ondelete="RESTRICT"), nullable=True,
    )
    scope_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedule_scopes.id", ondelete="RESTRICT"), nullable=True,
    )

    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WeeklyScheduleCommandRecord(Base):
    """Owner-scoped durable idempotency receipt for weekly atomic commands."""
    __tablename__ = "weekly_schedule_commands"
    __table_args__ = (Index("ix_weekly_commands_owner", "owner_id"),)

    owner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
