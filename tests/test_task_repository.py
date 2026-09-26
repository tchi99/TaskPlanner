from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain import Task, TaskStatus
from app.infrastructure.db import Base
from app.infrastructure.task_repository import SqlTaskRepository
from app.infrastructure import models  # noqa: F401


def test_sql_repository_persists_and_orders_inbox() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

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
        inbox = repository.list_inbox()

    assert [task.title for task in inbox] == ["Newer", "Older"]
