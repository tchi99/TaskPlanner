"""TP-022R migration retains previously accepted bookings and rejects data loss."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, target, action="upgrade"):
    subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        cwd=ROOT, check=True, capture_output=True, text=True,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )


def test_upgrade_preserves_legacy_booking_and_downgrade_guard(tmp_path):
    db = tmp_path / "tp022r.sqlite3"
    migrate(db, "0013_tp022c")
    identity, task = str(uuid4()), str(uuid4())
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO confirmed_time_blocks "
            "(id, week_start, task_id, segment_id, work_type_id, starts_at, ends_at) "
            "VALUES (?, '2026-10-05', ?, NULL, NULL, "
            "'2026-10-05T09:00:00-04:00', '2026-10-05T10:00:00-04:00')",
            (identity, task),
        )
    migrate(db, "head")
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version",
        ).fetchone() == ("0015_tp023a",)
        assert connection.execute(
            "SELECT id, status, revision FROM confirmed_time_blocks",
        ).fetchone() == (identity, "CONFIRMED", 1)
        history_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='history_events'",
        ).fetchone()[0]
        assert "TIME_BLOCK" in history_schema
    migrate(db, "0013_tp022c", "downgrade")
    with sqlite3.connect(db) as connection:
        assert "status" not in {
            row[1] for row in connection.execute("PRAGMA table_info(confirmed_time_blocks)")
        }
        assert connection.execute(
            "SELECT id FROM confirmed_time_blocks",
        ).fetchone() == (identity,)
    migrate(db, "head")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE confirmed_time_blocks SET status='CANCELLED', revision=2 "
            "WHERE id=?", (identity,),
        )
    try:
        migrate(db, "0013_tp022c", "downgrade")
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("downgrade must reject confirmed booking decisions")
