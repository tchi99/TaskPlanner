"""TP-022C additive migration retains historical reservations on SQLite."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, target):
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=ROOT, check=True, capture_output=True, text=True,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )


def test_accepted_transfer_column_does_not_rewrite_legacy_booking(tmp_path):
    db_path = tmp_path / "tp022c.db"
    migrate(db_path, "0012_tp022b")
    identity, task = str(uuid4()), str(uuid4())
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO confirmed_time_blocks "
            "(id, week_start, task_id, segment_id, work_type_id, starts_at, ends_at) "
            "VALUES (?, '2026-10-05', ?, NULL, NULL, "
            "'2026-10-05T09:00:00-04:00', '2026-10-05T10:00:00-04:00')",
            (identity, task),
        )
    migrate(db_path, "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0013_tp022c",
        )
        columns = {r[1] for r in connection.execute(
            "PRAGMA table_info(confirmed_time_blocks)"
        )}
        assert "transferred_from_work_type_id" in columns
        assert connection.execute(
            "SELECT id, transferred_from_work_type_id FROM confirmed_time_blocks"
        ).fetchone() == (identity, None)
        constraints = connection.execute(
            "PRAGMA foreign_key_list(confirmed_time_blocks)"
        ).fetchall()
        assert any(
            row[2] == "work_types" and row[3] == "transferred_from_work_type_id"
            and row[6] == "RESTRICT"
            for row in constraints
        )
    migrate(db_path, "0012_tp022b")
    with sqlite3.connect(db_path) as connection:
        assert "transferred_from_work_type_id" not in {
            row[1] for row in connection.execute(
                "PRAGMA table_info(confirmed_time_blocks)"
            )
        }
        assert connection.execute(
            "SELECT id FROM confirmed_time_blocks"
        ).fetchone() == (identity,)
