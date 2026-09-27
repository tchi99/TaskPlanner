from types import TracebackType

from sqlalchemy.orm import Session

from app.infrastructure.db import SessionLocal
from app.infrastructure.history_repository import SqlHistoryRepository
from app.infrastructure.reference_repositories import (
    SqlProjectRepository,
    SqlWorkTypeRepository,
)
from app.infrastructure.task_repository import SqlTaskRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.tasks = SqlTaskRepository(self.session)
        self.history = SqlHistoryRepository(self.session)
        self.projects = SqlProjectRepository(self.session)
        self.work_types = SqlWorkTypeRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self.session is not None
        if self.session.in_transaction():
            self.session.rollback()
        self.session.close()
        self.session = None

    def commit(self) -> None:
        assert self.session is not None
        self.session.commit()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()


def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork()
