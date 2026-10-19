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


def test_fresh_multiple_permissions_schema_with_priority_revision(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        assert {"eligibility_series", "eligibility_revisions",
                "eligibility_exceptions", "eligibility_exception_revisions"} <= tables(db)
        assert {"scope_id", "work_type_id", "owner_id", "version"} <= set(
            columns(db, "eligibility_series"))
        assert {"priority_rank", "number", "effective_from",
                "valid_until"} <= set(columns(db, "eligibility_revisions"))
        assert db.execute("SELECT COUNT(*) FROM eligibility_series").fetchone() == (0,)


def test_baseline_cannot_be_downgraded_to_a_historical_revision(tmp_path):
    path = fresh(tmp_path)
    result = migrate(path, command="downgrade", target="0016_tp024a")
    assert result.returncode != 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0020_tp026_fresh",)
