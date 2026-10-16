"""TP-022A additive Alembic upgrade preserves historical rows and checks."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def migrate(path: Path, revision: str):
    env = {**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )


def test_upgrade_preserves_manual_capacity_and_existing_audit(tmp_path):
    path = tmp_path / "legacy.db"
    migrate(path, "0010_tp080b")
    task_id, event_id, correlation_id, block_id = (str(uuid4()) for _ in range(4))
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO tasks (id,title,status,protection,created_at) "
            "VALUES (?, 'Old task', 'TODO', 'REPLANNABLE', ?)",
            (task_id, "2026-10-11 12:00:00"),
        )
        db.execute(
            "INSERT INTO availability_blocks (id,week_start,starts_at,ends_at) "
            "VALUES (?, '2026-10-05', ?, ?)",
            (block_id, "2026-10-05T08:00:00-04:00", "2026-10-05T09:00:00-04:00"),
        )
        db.execute(
            "INSERT INTO history_events "
            "(id,occurred_at,recorded_at,entity_type,entity_id,task_id,event_type,"
            "schema_version,source,correlation_id,payload) "
            "VALUES (?,?,?,'TASK',?,?,'TASK_CAPTURED',1,'USER',?,'{}')",
            (event_id, "2026-10-11 12:00:00", "2026-10-11 12:00:00",
             task_id, task_id, correlation_id),
        )
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016_tp024a",)
        assert db.execute("SELECT id FROM availability_blocks").fetchone() == (block_id,)
        assert db.execute("SELECT sequence FROM history_events WHERE id=?", (event_id,)).fetchone() == (1,)
        db.execute(
            "INSERT INTO history_events "
            "(id,occurred_at,recorded_at,entity_type,entity_id,event_type,"
            "schema_version,source,correlation_id,payload) "
            "VALUES (?,?,?,'AVAILABILITY_RULE',?,'AVAILABILITY_RULE_CREATED',1,'USER',?,'{}')",
            (str(uuid4()), "2026-10-12 12:00:00", "2026-10-12 12:00:00",
             str(uuid4()), str(uuid4())),
        )
        assert db.execute("SELECT count(*) FROM history_events").fetchone()[0] == 2
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='recurring_availability_revisions'"
        ).fetchone() is not None
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO recurring_availability_rules "
                       "(id,owner_id,version,created_at) VALUES (?, 'owner',0,?)",
                       (str(uuid4()), "2026-10-12 12:00:00"))


def test_fresh_database_has_revision_schema(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016_tp024a",)
        columns = {column[1] for column in db.execute(
            "PRAGMA table_info(recurring_availability_revisions)"
        )}
        assert {"effective_from", "valid_until", "timezone_name", "days_of_week",
                "mode", "start_fold", "end_fold", "recorded_at"} <= columns
