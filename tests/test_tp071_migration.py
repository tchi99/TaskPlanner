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


def test_fresh_work_sessions_keep_single_active_partial_uniqueness(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert {"task_id", "segment_id", "active_since", "active_seconds",
                "revision", "status"} <= set(columns(db, "work_sessions"))
        index_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uq_work_sessions_single_active'"
        ).fetchone()[0]
        assert "UNIQUE" in index_sql.upper()
        assert "WHERE" in index_sql.upper() and "ACTIVE" in index_sql
        assert db.execute("SELECT COUNT(*) FROM work_sessions").fetchone() == (0,)
