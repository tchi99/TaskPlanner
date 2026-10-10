"""Additive 0009 migration preserves task rows and enforces one active session."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def _upgrade(path: Path, revision: str) -> None:
    env = {**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True)


def test_additive_migration_and_partial_uniqueness(tmp_path):
    path = tmp_path / "work.db"
    _upgrade(path, "0008_tp070")
    task_id = str(uuid4())
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO tasks (id,title,status,protection,created_at) "
            "VALUES (?, ?, 'TODO', 'REPLANNABLE', ?)",
            (task_id, "Old task", "2026-10-10 12:00:00"),
        )
    _upgrade(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone() == ("Old task",)
        table = {row[1] for row in db.execute("PRAGMA table_info(work_sessions)")}
        assert {"task_id", "segment_id", "active_since", "active_seconds", "revision"} <= table
        template = ("INSERT INTO work_sessions (id,task_id,started_at,active_since,"
                    "active_seconds,interruptions,status,revision) VALUES (?,?,?, ?,0,0,?,1)")
        stamp = "2026-10-10 12:00:00"
        db.execute(template, (str(uuid4()), task_id, stamp, stamp, "ACTIVE"))
        with __import__("pytest").raises(sqlite3.IntegrityError):
            db.execute(template, (str(uuid4()), task_id, stamp, stamp, "ACTIVE"))
