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


def test_real_parent_is_required_at_database_boundary(tmp_path):
    path = fresh(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        cols = columns(db, "work_types")
        assert cols["scope_id"][3] == 1
        assert "is_compatibility" not in columns(db, "schedule_scopes")
        assert "work_type_scope_assignments" not in tables(db)
        fk = {row[3]: (row[2], row[6]) for row in db.execute(
            "PRAGMA foreign_key_list(work_types)")}
        assert fk["scope_id"] == ("schedule_scopes", "RESTRICT")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO work_types(id,name,scope_id,version)"
                       " VALUES (?, 'Orphan', ?, 1)", (str(uuid4()), str(uuid4())))
        parent = str(uuid4())
        db.execute("INSERT INTO schedule_scopes(id,owner_id,name,state,version)"
                   " VALUES (?, 'owner', 'Travail', 'ACTIVE', 1)", (parent,))
        leaf = str(uuid4())
        db.execute("INSERT INTO work_types(id,name,scope_id,version)"
                   " VALUES (?, 'Focus', ?, 1)", (leaf, parent))
        assert db.execute("SELECT scope_id FROM work_types WHERE id=?", (leaf,)).fetchone() == (parent,)
