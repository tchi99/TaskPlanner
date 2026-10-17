"""TP-080D: destructive-test-safe backup/restore drill on disposable local Postgres.

NEVER point this module at Supabase or production. The only accepted source is
localhost / taskplanner_test. A random, *new* local database is restored and
deleted; the original database is never overwritten. No SQL credentials, row
contents or command stderr are printed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

SCHEMA = "taskplanner"
SOURCE_DB = "taskplanner_test"


class DrillError(RuntimeError):
    """A safety requirement or validation failed."""


def validate_test_url(raw: str | None) -> URL:
    if not raw:
        raise DrillError("TASKPLANNER_PG_TEST_URL is required")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise DrillError("Invalid test database URL") from exc
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in ("localhost", "127.0.0.1")
        or url.database != SOURCE_DB
        or not url.username
    ):
        raise DrillError("Only the local taskplanner_test PostgreSQL database is permitted")
    if url.query.get("sslmode", "disable") not in ("disable", "require", "verify-full"):
        raise DrillError("Unsupported local database SSL mode")
    return url


def connection_params(url: URL, database: str) -> dict[str, object]:
    return {
        "host": url.host,
        "port": url.port or 5432,
        "dbname": database,
        "user": url.username,
        "password": url.password or "",
        "sslmode": url.query.get("sslmode", "disable"),
        "connect_timeout": 5,
    }


def process_env(url: URL) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key != "TASKPLANNER_PG_TEST_URL"}
    env.update({
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGDATABASE": SOURCE_DB,
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
        "PGSSLMODE": str(url.query.get("sslmode", "disable")),
        "PGCONNECT_TIMEOUT": "5",
    })
    return env


def snapshot(url: URL, database: str) -> tuple:
    """Compare all schema rows, migration version and sequence positions.

    Hashes are comparison-only, never printed. This is sized for the disposable
    CI fixture, not a production-scale database export.
    """
    with psycopg.connect(**connection_params(url, database)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = %s ORDER BY tablename", (SCHEMA,)
            )
            names = [row[0] for row in cursor.fetchall()]
            if not {"alembic_version", "projects", "tasks", "history_events"} <= set(names):
                raise DrillError("Missing migrated application tables")
            result = []
            for name in names:
                query = sql.SQL("SELECT to_jsonb(t)::text FROM {} AS t").format(
                    sql.Identifier(SCHEMA, name)
                )
                cursor.execute(query)
                rows = sorted(row[0] for row in cursor.fetchall())
                digest = hashlib.sha256()
                for row in rows:
                    digest.update(row.encode("utf-8"))
                    digest.update(b"\n")
                result.append((name, len(rows), digest.hexdigest()))
            cursor.execute(
                "SELECT sequencename, last_value FROM pg_catalog.pg_sequences "
                "WHERE schemaname = %s ORDER BY sequencename", (SCHEMA,)
            )
            sequences = tuple(cursor.fetchall())
            cursor.execute(
                sql.SQL("SELECT version_num FROM {}").format(
                    sql.Identifier(SCHEMA, "alembic_version")
                )
            )
            revisions = tuple(sorted(row[0] for row in cursor.fetchall()))
            if revisions != ("0019_tp025d",):
                raise DrillError("Unexpected migration version")
            return tuple(result), sequences, revisions


def safe_command(arguments: list[str], env: dict[str, str]) -> None:
    # Do not echo arguments, environment, stderr or stdout: a subprocess or
    # connection library may accidentally include operational credentials.
    outcome = subprocess.run(
        arguments, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=False,
        timeout=120,
    )
    if outcome.returncode != 0:
        raise DrillError(f"PostgreSQL tool exited with code {outcome.returncode}")


def run_drill(raw_url: str | None) -> int:
    url = validate_test_url(raw_url)
    for tool in ("pg_dump", "pg_restore"):
        if not shutil.which(tool):
            raise DrillError("pg_dump and pg_restore are required")
    original = snapshot(url, SOURCE_DB)
    # Ensure this is a meaningful nonempty fixture, not a vacuous empty restore.
    rows = {name: count for name, count, _ in original[0]}
    if rows.get("tasks", 0) < 1 or rows.get("history_events", 0) < 1:
        raise DrillError("Source fixture must contain tasks and history")
    restore_db = "taskplanner_restore_test_" + uuid4().hex[:16]
    created = False
    try:
        with psycopg.connect(**connection_params(url, SOURCE_DB), autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_db))
            )
            created = True

        with tempfile.TemporaryDirectory(prefix="taskplanner-restore-") as temp:
            backup_path = Path(temp) / "taskplanner.dump"
            env = process_env(url)
            safe_command([
                "pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "--schema=" + SCHEMA, "--file=" + str(backup_path),
            ], env)
            if not backup_path.is_file() or backup_path.stat().st_size == 0:
                raise DrillError("No usable backup was produced")
            safe_command([
                "pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
                "--dbname=" + restore_db, str(backup_path),
            ], env)
            restored = snapshot(url, restore_db)
            if restored != original:
                raise DrillError("Restore differs in rows, migration or sequences")
        print("TP-080D disposable PostgreSQL backup/restore: VERIFIED")
        return 0
    finally:
        if created:
            # Drop ONLY the randomly created database, NEVER taskplanner_test.
            with psycopg.connect(
                **connection_params(url, SOURCE_DB), autocommit=True
            ) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(restore_db)
                    )
                )


def main() -> int:
    try:
        return run_drill(os.getenv("TASKPLANNER_PG_TEST_URL"))
    except (DrillError, psycopg.Error, OSError, subprocess.TimeoutExpired):
        # Explicitly redact details; drivers can embed the DSN in exceptions.
        print("TP-080D restore drill FAILED (details suppressed for safety)",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
