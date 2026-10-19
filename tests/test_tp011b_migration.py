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


def test_fresh_root_contains_capture_and_audit_without_seeded_history(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0020_tp026_fresh",)
        assert {"tasks", "task_segments", "history_events", "projects"} <= tables(db)
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM history_events").fetchone() == (0,)


def test_preexisting_legacy_capture_refuses_upgrade_without_data_loss(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        db.execute("INSERT INTO tasks VALUES (?, ?)", (str(uuid4()), "Preserve me"))
    result = migrate(path)
    assert result.returncode != 0
    assert "fresh empty database" in result.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM tasks").fetchone() == ("Preserve me",)
        assert "history_events" not in tables(db)
