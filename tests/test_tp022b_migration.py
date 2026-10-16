"""TP-022B additive migration from TP-022A, with no booking rewrite."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, revision):
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                   cwd=ROOT, env={**os.environ,
                   "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
                   check=True, capture_output=True, text=True)


def test_new_table_and_history_constraint_preserve_legacy_rows(tmp_path):
    path = tmp_path / "existing.db"
    migrate(path, "0011_tp022a")
    block_id = str(uuid4())
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO availability_blocks (id,week_start,starts_at,ends_at) "
            "VALUES (?,'2026-10-05','2026-10-05T09:00:00-04:00','2026-10-05T10:00:00-04:00')",
            (block_id,),
        )
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016_tp024a",)
        assert db.execute("SELECT id FROM availability_blocks").fetchone() == (block_id,)
        columns = {column[1] for column in db.execute(
            "PRAGMA table_info(availability_exceptions)")}
        assert {"id", "owner_id", "version", "rule_id", "original_local_date",
                "starts_at", "ends_at", "timezone_name", "mode"} <= columns
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name='confirmed_time_blocks'").fetchone()
