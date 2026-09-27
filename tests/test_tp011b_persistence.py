from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.history import (
    HistoryEvent,
    HistorySource,
    build_history_events,
)
from app.application.tasks import CaptureTaskCommand, capture_task
from app.domain import (
    DomainEntityType,
    DomainFact,
    DomainFactType,
    FactRole,
    Project,
    SegmentStatus,
    SegmentStatusChanged,
    Task,
    TaskAggregate,
    TaskSegment,
    TaskStatus,
    TaskStatusChanged,
    WorkType,
)
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.history_repository import SqlHistoryRepository
from app.infrastructure.models import (
    HistoryEventRecord,
    TaskRecord,
    TaskSegmentRecord,
)
from app.infrastructure.task_repository import SqlTaskRepository
from app.infrastructure.uow import SqlAlchemyUnitOfWork

UTC = timezone.utc
EASTERN = timezone(timedelta(hours=-4))


def _engine_and_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def _task_record(**overrides) -> TaskRecord:
    values = {
        "id": str(uuid4()),
        "title": "Task",
        "project_id": None,
        "notes": None,
        "status": "INBOX",
        "protection": "REPLANNABLE",
        "work_type_id": None,
        "estimated_minutes": None,
        "due_at": None,
        "created_at": datetime(2026, 9, 27, 14, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return TaskRecord(**values)


def _assert_integrity_error(engine, record) -> None:
    with Session(engine) as session:
        session.add(record)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_sqlite_enforces_operational_foreign_keys_and_accepts_valid_relations() -> None:
    engine, factory = _engine_and_factory()
    missing_project = str(uuid4())
    missing_type = str(uuid4())

    _assert_integrity_error(engine, _task_record(project_id=missing_project))
    _assert_integrity_error(engine, _task_record(work_type_id=missing_type))

    _assert_integrity_error(
        engine,
        TaskSegmentRecord(
            id=str(uuid4()),
            task_id=str(uuid4()),
            title="Missing task",
            status="TODO",
            position=0,
            work_type_id=None,
            estimated_minutes=None,
        ),
    )

    task = Task(title="Parent", status=TaskStatus.TODO)
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.commit()

    _assert_integrity_error(
        engine,
        TaskSegmentRecord(
            id=str(uuid4()),
            task_id=str(task.id),
            title="Missing type",
            status="TODO",
            position=0,
            work_type_id=missing_type,
            estimated_minutes=None,
        ),
    )

    project = Project(title="Valid project")
    work_type = WorkType(name="Deep work")
    valid_task = Task(
        title="Valid task",
        project_id=project.id,
        work_type_id=work_type.id,
        status=TaskStatus.TODO,
    )
    aggregate = TaskAggregate(
        valid_task,
        (
            TaskSegment(
                task_id=valid_task.id,
                title="Valid segment",
                position=0,
                work_type_id=work_type.id,
            ),
        ),
    )
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.projects.add(project)
        uow.work_types.add(work_type)
        uow.tasks.add_aggregate(aggregate)
        uow.commit()

    with Session(engine) as session:
        assert session.get(TaskRecord, str(valid_task.id)) is not None
        segment = session.scalar(
            select(TaskSegmentRecord).where(
                TaskSegmentRecord.task_id == str(valid_task.id)
            )
        )
        assert segment is not None
        assert segment.work_type_id == str(work_type.id)


def test_project_work_type_and_aggregate_round_trip_preserves_segment_order() -> None:
    _, factory = _engine_and_factory()
    project = Project(title="P", description="Description")
    work_type = WorkType(name="Focused", description="Quiet work")
    task = Task(
        title="Parent",
        project_id=project.id,
        work_type_id=work_type.id,
        status=TaskStatus.TODO,
        estimated_minutes=120,
    )
    later = TaskSegment(
        task_id=task.id,
        title="Later",
        status=SegmentStatus.TODO,
        position=7,
    )
    earlier = TaskSegment(
        task_id=task.id,
        title="Earlier",
        status=SegmentStatus.IN_PROGRESS,
        position=2,
        estimated_minutes=30,
        work_type_id=work_type.id,
    )
    aggregate = TaskAggregate(task, (later, earlier))

    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.projects.add(project)
        uow.work_types.add(work_type)
        uow.tasks.add_aggregate(aggregate)
        uow.commit()

    with SqlAlchemyUnitOfWork(factory) as uow:
        reloaded_project = uow.projects.get(project.id)
        reloaded_type = uow.work_types.get(work_type.id)
        reloaded = uow.tasks.get_aggregate(task.id)

    assert reloaded_project == project
    assert reloaded_type == work_type
    assert reloaded is not None
    assert reloaded.task == task
    assert [segment.position for segment in reloaded.segments] == [2, 7]
    assert [segment.id for segment in reloaded.segments] == [earlier.id, later.id]


def test_fact_mapping_keeps_source_correlation_and_causation_explicit() -> None:
    task = Task(title="Parent", status=TaskStatus.TODO)
    segment = TaskSegment(task_id=task.id, title="First", position=0)
    facts = (
        DomainFact(
            event_type=DomainFactType.SEGMENT_STARTED,
            entity_type=DomainEntityType.SEGMENT,
            entity_id=segment.id,
            task_id=task.id,
            role=FactRole.DIRECT,
            payload=SegmentStatusChanged(
                SegmentStatus.TODO, SegmentStatus.IN_PROGRESS
            ),
        ),
        DomainFact(
            event_type=DomainFactType.TASK_STARTED,
            entity_type=DomainEntityType.TASK,
            entity_id=task.id,
            task_id=task.id,
            role=FactRole.PROPAGATED,
            payload=TaskStatusChanged(
                TaskStatus.TODO, TaskStatus.IN_PROGRESS
            ),
        ),
    )
    fixed = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)
    correlation_id = uuid4()

    events = build_history_events(
        facts,
        direct_source=HistorySource.USER,
        correlation_id=correlation_id,
        occurred_at=fixed,
        clock=lambda: fixed,
    )

    direct, propagated = events
    assert direct.source is HistorySource.USER
    assert propagated.source is HistorySource.SYSTEM_RULE
    assert direct.correlation_id == correlation_id == propagated.correlation_id
    assert direct.causation_id is None
    assert propagated.causation_id == direct.id
    assert direct.payload == {"before": "TODO", "after": "IN_PROGRESS"}
    assert propagated.payload == {"before": "TODO", "after": "IN_PROGRESS"}


def test_capture_commits_task_and_minimal_history_together() -> None:
    engine, factory = _engine_and_factory()
    due_at = datetime(2026, 9, 27, 10, 0, tzinfo=EASTERN)

    task = capture_task(
        SqlAlchemyUnitOfWork(factory),
        CaptureTaskCommand(
            title="Private title",
            notes="Private notes",
            due_at=due_at,
            estimated_minutes=45,
        ),
    )

    with Session(engine) as session:
        persisted = SqlTaskRepository(session).get(task.id)
        events = session.scalars(select(HistoryEventRecord)).all()

    assert persisted is not None
    assert persisted.status is TaskStatus.INBOX
    assert persisted.created_at == task.created_at.astimezone(UTC)
    assert persisted.due_at == datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
    assert len(events) == 1
    event = events[0]
    UUID(event.id)
    UUID(event.correlation_id)
    assert event.event_type == "TASK_CAPTURED"
    assert event.entity_type == "TASK"
    assert event.entity_id == str(task.id)
    assert event.task_id == str(task.id)
    assert event.schema_version == 1
    assert event.source == "USER"
    assert event.reason_code is None
    assert event.causation_id is None
    assert event.occurred_at == task.created_at.astimezone(UTC)
    assert event.recorded_at.tzinfo is not None
    assert event.payload == {
        "status": "INBOX",
        "estimated_minutes": 45,
        "work_type_id": None,
    }
    assert "title" not in event.payload
    assert "notes" not in event.payload


def test_task_and_history_datetimes_round_trip_as_same_utc_instants() -> None:
    engine, factory = _engine_and_factory()
    created_at = datetime(2026, 9, 27, 9, 30, tzinfo=EASTERN)
    due_at = datetime(2026, 9, 27, 10, 0, tzinfo=EASTERN)
    occurred_at = datetime(2026, 9, 27, 10, 15, tzinfo=EASTERN)
    recorded_at = datetime(2026, 9, 27, 10, 16, tzinfo=EASTERN)
    task = Task(
        title="UTC",
        status=TaskStatus.INBOX,
        created_at=created_at,
        due_at=due_at,
    )
    event = HistoryEvent(
        id=uuid4(),
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        entity_type="TASK",
        entity_id=task.id,
        task_id=task.id,
        event_type="TASK_CAPTURED",
        schema_version=1,
        source=HistorySource.USER,
        reason_code=None,
        correlation_id=uuid4(),
        causation_id=None,
        payload={},
    )

    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.tasks.add(task)
        uow.history.append(event)
        uow.commit()

    with Session(engine) as session:
        reloaded_task = SqlTaskRepository(session).get(task.id)
        reloaded_event = session.scalar(select(HistoryEventRecord))

    assert reloaded_task is not None
    assert reloaded_task.created_at == datetime(
        2026, 9, 27, 13, 30, tzinfo=UTC
    )
    assert reloaded_task.due_at == datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
    assert reloaded_event is not None
    assert reloaded_event.occurred_at == datetime(
        2026, 9, 27, 14, 15, tzinfo=UTC
    )
    assert reloaded_event.recorded_at == datetime(
        2026, 9, 27, 14, 16, tzinfo=UTC
    )


class InvalidHistoryRepository(SqlHistoryRepository):
    def append_many(self, events) -> None:
        for event in events:
            self._session.add(
                HistoryEventRecord(
                    id=str(event.id),
                    occurred_at=event.occurred_at,
                    recorded_at=event.recorded_at,
                    entity_type=event.entity_type,
                    entity_id=str(event.entity_id),
                    task_id=str(event.task_id) if event.task_id else None,
                    event_type=event.event_type,
                    schema_version=event.schema_version,
                    source="INVALID_SOURCE",
                    reason_code=None,
                    correlation_id=str(event.correlation_id),
                    causation_id=None,
                    payload=event.payload,
                )
            )


class InvalidTaskRepository(SqlTaskRepository):
    def add(self, task: Task) -> Task:
        record = self._record(task)
        record.estimated_minutes = 0
        self._session.add(record)
        return task


class HistoryFailureUnitOfWork(SqlAlchemyUnitOfWork):
    def __enter__(self):
        super().__enter__()
        assert self.session is not None
        self.history = InvalidHistoryRepository(self.session)
        return self


class OperationalFailureUnitOfWork(SqlAlchemyUnitOfWork):
    def __enter__(self):
        super().__enter__()
        assert self.session is not None
        self.tasks = InvalidTaskRepository(self.session)
        return self


def _counts(engine) -> tuple[int, int]:
    with Session(engine) as session:
        tasks = session.scalar(select(func.count()).select_from(TaskRecord))
        events = session.scalar(select(func.count()).select_from(HistoryEventRecord))
    return int(tasks or 0), int(events or 0)


def test_history_failure_rolls_back_operational_state() -> None:
    engine, factory = _engine_and_factory()

    with pytest.raises(IntegrityError):
        capture_task(
            HistoryFailureUnitOfWork(factory),
            CaptureTaskCommand(title="Must rollback"),
        )

    assert _counts(engine) == (0, 0)


def test_operational_failure_rolls_back_prepared_history() -> None:
    engine, factory = _engine_and_factory()

    with pytest.raises(IntegrityError):
        capture_task(
            OperationalFailureUnitOfWork(factory),
            CaptureTaskCommand(title="Must rollback", estimated_minutes=15),
        )

    assert _counts(engine) == (0, 0)


def test_history_repository_normal_interface_is_append_only() -> None:
    public_methods = {
        name
        for name in dir(SqlHistoryRepository)
        if not name.startswith("_")
    }
    assert public_methods == {"append", "append_many"}
