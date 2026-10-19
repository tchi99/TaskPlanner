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


def test_fresh_recurring_schema_has_empty_rules_revisions_and_audit(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert {"recurring_availability_rules",
                "recurring_availability_revisions", "history_events"} <= tables(db)
        for table in ("recurring_availability_rules",
                      "recurring_availability_revisions", "history_events"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_repeated_baseline_upgrade_is_idempotent(tmp_path):
    path = fresh(tmp_path)
    again = migrate(path)
    assert again.returncode == 0, again.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0020_tp026_fresh",)
