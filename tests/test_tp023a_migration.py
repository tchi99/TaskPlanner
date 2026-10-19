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


def test_fresh_atomic_weekly_command_receipt_is_owner_scoped(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert "weekly_schedule_commands" in tables(db)
        cols = columns(db, "weekly_schedule_commands")
        assert {"owner_id", "command_id", "payload_hash",
                "result", "created_at"} <= set(cols)
        assert cols["owner_id"][5] > 0 and cols["command_id"][5] > 0
        assert db.execute("SELECT COUNT(*) FROM weekly_schedule_commands").fetchone() == (0,)


def test_fresh_root_has_no_dated_work_type_affiliation_tables(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert "work_type_scope_assignments" not in tables(db)
        assert "work_type_scope_versions" not in tables(db)
