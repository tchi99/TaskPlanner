"""TP-026A: fresh PostgreSQL root and owner-scoped persistence on disposable CI."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.infrastructure.db import create_taskplanner_engine
from app.infrastructure.models import ScheduleScopeRecord, WorkTypeRecord

ROOT = Path(__file__).resolve().parents[1]


def test_pg_fresh_migration_fk_owner_and_immutable_scope():
    raw = os.getenv("TASKPLANNER_PG_TEST_URL")
    if not raw:
        pytest.skip("Only disposable local PostgreSQL CI runs this test")
    url = make_url(raw)
    if (url.host not in ("localhost", "127.0.0.1")
            or url.database != "taskplanner_test"
            or url.drivername != "postgresql+psycopg"):
        pytest.fail("Refusing schema creation outside disposable taskplanner_test")
    schema = "tp026a_" + uuid4().hex[:16]
    admin = create_engine(raw, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        env = {**os.environ, "TASKPLANNER_DATABASE_URL": raw,
               "TASKPLANNER_DATABASE_SCHEMA": schema,
               "TASKPLANNER_ENV": "test", "TASKPLANNER_AUTH_MODE": "local"}
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                cwd=ROOT, capture_output=True, text=True,
                                env=env, check=False)
        assert result.returncode == 0, result.stderr
        engine = create_taskplanner_engine(raw, environment="test", schema=schema)
        try:
            tables = set(inspect(engine).get_table_names(schema=schema))
            assert {"work_types", "schedule_scopes", "eligibility_series",
                    "alembic_version"} <= tables
            assert "work_type_scope_assignments" not in tables
            with Session(engine) as session:
                owner = "pg-026a-owner"
                parent = uuid4()
                leaf = uuid4()
                session.add(ScheduleScopeRecord(
                    id=str(parent), owner_id=owner, name="Travail",
                    state="ACTIVE", version=1))
                session.flush()
                session.add(WorkTypeRecord(
                    id=str(leaf), name="Focus", scope_id=str(parent), version=1))
                session.commit()
                row = session.scalar(select(WorkTypeRecord).where(
                    WorkTypeRecord.id == str(leaf)))
                assert row.scope_id == str(parent)
                assert row.version == 1
                assert session.scalar(select(ScheduleScopeRecord).where(
                    ScheduleScopeRecord.owner_id == "another-user")) is None
            with engine.connect() as connection:
                assert connection.scalar(text(
                    "SELECT version_num FROM alembic_version")) == "0020_tp026_fresh"
        finally:
            engine.dispose()
    finally:
        # Safe only because schema name is generated here AND target local DB
        # was checked. Never delete existing schemas or remote environments.
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            admin.dispose()
