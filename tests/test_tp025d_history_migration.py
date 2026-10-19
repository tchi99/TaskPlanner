"""TP-026 fresh-only Alembic contract (ADR-0025).

Historical upgrade-in-place assertions are no longer valid. Every check below
exercises the new installation or the fail-closed guard without bypassing CI.
"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, *, command="upgrade", target="head"):
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, target], cwd=ROOT,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}",
             "TASKPLANNER_ENV": "test", "TASKPLANNER_AUTH_MODE": "local"},
        capture_output=True, text=True, check=False,
    )


def fresh(tmp_path):
    path = tmp_path / "fresh.sqlite"
    result = migrate(path)
    assert result.returncode == 0, result.stderr
    return path


def tables(db):
    return {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def columns(db, name):
    return {row[1]: row for row in db.execute(f"PRAGMA table_info({name})")}


def test_fresh_history_supports_current_eligibility_and_booking_audit(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        table_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='history_events'"
        ).fetchone()[0]
        for event_type in ("ELIGIBILITY_SERIES", "TIME_BLOCK",
                           "AVAILABILITY_EXCEPTION", "TASK"):
            assert event_type in table_sql
        assert {"sequence", "correlation_id", "payload",
                "schema_version", "source"} <= set(columns(db, "history_events"))
        assert db.execute("SELECT COUNT(*) FROM history_events").fetchone() == (0,)


def test_no_stale_audit_or_compatibility_parent_on_clean_install(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM schedule_scopes").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM scope_change_audit").fetchone() == (0,)
        assert "is_compatibility" not in columns(db, "schedule_scopes")
