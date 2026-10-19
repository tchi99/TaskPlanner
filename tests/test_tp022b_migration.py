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


def test_fresh_exceptions_and_conflict_bookings_start_empty(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert {"availability_exceptions", "confirmed_time_blocks"} <= tables(db)
        assert {"owner_id", "rule_id", "original_local_date", "version",
                "starts_at", "ends_at", "action"} <= set(columns(db, "availability_exceptions"))
        assert db.execute("SELECT COUNT(*) FROM availability_exceptions").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM confirmed_time_blocks").fetchone() == (0,)
