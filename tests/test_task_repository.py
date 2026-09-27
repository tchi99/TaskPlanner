from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain import Task, TaskStatus
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.task_repository import SqlTaskRepository


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_sql_repository_persists_and_orders_inbox_after_owner_commits() -> None:
    engine = _engine()
    older = Task(
        title="Older",
        status=TaskStatus.INBOX,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    newer = Task(
        title="Newer",
        status=TaskStatus.INBOX,
        created_at=datetime.now(timezone.utc),
    )
    ready = Task(title="Clarified", status=TaskStatus.TODO)

    with Session(engine) as session:
        repository = SqlTaskRepository(session)
        repository.add(older)
        repository.add(newer)
        repository.add(ready)
        session.commit()

    with Session(engine) as session:
        inbox = SqlTaskRepository(session).list_inbox()

    assert [task.title for task in inbox] == ["Newer", "Older"]


def test_sql_repository_does_not_commit_its_own_writes() -> None:
    engine = _engine()
    task = Task(title="Uncommitted", status=TaskStatus.INBOX)

    with Session(engine) as session:
        SqlTaskRepository(session).add(task)

    with Session(engine) as session:
        assert SqlTaskRepository(session).get(task.id) is None
