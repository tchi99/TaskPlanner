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


def test_new_booking_resolution_and_audit_schema_is_initialized_empty(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert {"confirmed_time_blocks", "time_block_confirmation_commands",
                "history_events"} <= tables(db)
        assert {"status", "revision"} <= set(columns(db, "confirmed_time_blocks"))
        assert db.execute("SELECT COUNT(*) FROM time_block_confirmation_commands").fetchone() == (0,)


def test_destructive_downgrade_is_refused_without_dropping_data(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO projects(id,title,status) VALUES (?, 'Keep me', 'ACTIVE')",
                   (str(uuid4()),))
    refused = migrate(path, command="downgrade", target="base")
    assert refused.returncode != 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM projects").fetchone() == ("Keep me",)
