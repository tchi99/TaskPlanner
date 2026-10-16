from types import TracebackType

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.capacity_repository import SqlAvailabilityRepository
from app.infrastructure.db import SessionLocal
from app.infrastructure.history_repository import SqlHistoryReadRepository, SqlHistoryRepository
from app.infrastructure.reference_repositories import (
    SqlProjectRepository,
    SqlWorkTypeRepository,
)
from app.infrastructure.task_repository import SqlTaskRepository
from app.infrastructure.time_block_repository import SqlConfirmedTimeBlockRepository
from app.infrastructure.daily_repository import SqlDailyReviewRepository
from app.infrastructure.weekly_repository import SqlWeeklyReviewRepository
from app.infrastructure.resume_repository import SqlResumePointRepository
from app.infrastructure.work_session_repository import SqlWorkSessionRepository
from app.infrastructure.availability_exception_repository import SqlAvailabilityExceptionRepository
from app.infrastructure.recurring_availability_repository import SqlRecurringAvailabilityRepository
from app.infrastructure.weekly_schedule_repository import SqlWeeklyScheduleCommandRepository
from app.infrastructure.schedule_scope_repository import SqlScheduleScopeRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.availability = SqlAvailabilityRepository(self.session)
        self.recurring_availability = SqlRecurringAvailabilityRepository(self.session)
        self.availability_exceptions = SqlAvailabilityExceptionRepository(self.session)
        self.weekly_commands = SqlWeeklyScheduleCommandRepository(self.session)
        self.time_blocks = SqlConfirmedTimeBlockRepository(self.session)
        self.daily_reviews = SqlDailyReviewRepository(self.session)
        self.weekly_reviews = SqlWeeklyReviewRepository(self.session)
        self.tasks = SqlTaskRepository(self.session)
        self.resume_points = SqlResumePointRepository(self.session)
        self.work_sessions = SqlWorkSessionRepository(self.session)
        self.history = SqlHistoryRepository(self.session)
        self.history_read = SqlHistoryReadRepository(self.session)
        self.projects = SqlProjectRepository(self.session)
        self.work_types = SqlWorkTypeRepository(self.session)
        self.schedule_scopes = SqlScheduleScopeRepository(self.session)
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

    def lock_planning(self) -> None:
        """Serialize confirmed booking and availability writes across workers.

        SQLite takes its write lock before reading; PostgreSQL holds a
        transaction-scoped advisory lock until commit or rollback.
        """
        assert self.session is not None
        connection = self.session.connection()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(246802468)"))
        else:
            raise RuntimeError("unsupported planning transaction dialect")

    def commit(self) -> None:
        assert self.session is not None
        self.session.commit()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()


def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork()
