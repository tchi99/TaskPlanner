"""SQLAlchemy engine setup shared by FastAPI and the Alembic migration runner."""
from collections.abc import Generator
import re
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_taskplanner_engine(
    database_url: str,
    *,
    environment: str = "development",
    schema: str = "taskplanner",
    migrations: bool = False,
) -> Engine:
    """Use a private PG schema; TLS is mandatory except in isolated CI tests.

    The schema must already exist. Never create schemas or apply migrations in
    application workers. Session pooling works with Supabase's session pooler;
    transaction pooler is intentionally not a supported endpoint here.
    """
    url = make_url(database_url)
    kwargs: dict[str, object] = {}
    connect_args: dict[str, object] = {}

    if url.get_backend_name() == "postgresql":
        if url.drivername != "postgresql+psycopg":
            raise ValueError("PostgreSQL requires the postgresql+psycopg driver")
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema) or schema in ("public", "pg_catalog"):
            raise ValueError("PostgreSQL requires a private, unexposed schema name")
        sslmode = url.query.get("sslmode")
        if isinstance(sslmode, tuple):
            raise ValueError("Only one PostgreSQL sslmode is permitted")
        if environment != "test" and sslmode not in (None, "require", "verify-ca", "verify-full"):
            raise ValueError("PostgreSQL TLS must be required")
        if environment != "test":
            connect_args["sslmode"] = sslmode or "require"
        # libpq options run when establishing the connection, before reflection
        # and before any SQLAlchemy/Alembic transaction starts.
        connect_args["options"] = f"-csearch_path={schema}"
        kwargs["pool_pre_ping"] = True
        if not migrations:
            kwargs.update(pool_size=3, max_overflow=2, pool_timeout=30, pool_recycle=1800)
    elif url.get_backend_name() == "sqlite":
        if environment == "production":
            raise ValueError("Production persistence requires PostgreSQL")
        connect_args["check_same_thread"] = False
    else:
        raise ValueError("Only SQLite and PostgreSQL are supported")

    if migrations:
        kwargs["poolclass"] = NullPool
    return create_engine(url, connect_args=connect_args, **kwargs)


settings = get_settings()
engine = create_taskplanner_engine(
    settings.database_url, environment=settings.env, schema=settings.database_schema
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
