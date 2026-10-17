"""TP-025D audit migration: additive types, old history and guarded downgrade."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]

_SQL = (
    "INSERT INTO history_events "
    "(id,occurred_at,recorded_at,entity_type,entity_id,event_type,"
    "schema_version,source,correlation_id,payload) "
    "VALUES (?, '2026-10-16 20:00:00', '2026-10-16 20:00:00',"
    "?, ?, ?, 1, 'USER', ?, '{}')"
)


def migrate(path: Path, command: str, version: str, *, success: bool = True) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, version],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )
    assert (result.returncode == 0) == success, result.stderr


def write_audit(db, entity_type: str, event_type: str) -> str:
    identifier = str(uuid4())
    db.execute(_SQL, (str(uuid4()), entity_type, identifier, event_type, str(uuid4())))
    return identifier


def test_upgrade_keeps_existing_audit_and_accepts_eligibility_series(tmp_path):
    path = tmp_path / "history.sqlite"
    migrate(path, "upgrade", "0018_tp025b")
    with sqlite3.connect(path) as db:
        old_id = write_audit(db, "AVAILABILITY_RULE", "AVAILABILITY_RULE_CHANGED")
        before = db.execute(
            "SELECT sequence FROM history_events WHERE entity_id=?", (old_id,)
        ).fetchone()[0]
    migrate(path, "upgrade", "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0019_tp025d",)
        assert db.execute("SELECT sequence FROM history_events WHERE entity_id=?",
                          (old_id,)).fetchone()[0] == before
        new_id = write_audit(db, "ELIGIBILITY_SERIES", "ELIGIBILITY_SERIES_CHANGED")
        assert db.execute("SELECT entity_type FROM history_events WHERE entity_id=?",
                          (new_id,)).fetchone() == ("ELIGIBILITY_SERIES",)
        assert db.execute("SELECT COUNT(*) FROM history_events").fetchone()[0] == 2
        names = {row[1] for row in db.execute("PRAGMA index_list(history_events)")}
        assert {"ix_history_events_task_sequence", "ix_history_events_entity_sequence",
                "ix_history_events_correlation_sequence"} <= names
        with pytest.raises(sqlite3.IntegrityError):
            write_audit(db, "UNKNOWN", "INVALID_EVENT")
    migrate(path, "downgrade", "0018_tp025b", success=False)


def test_downgrade_without_new_audit_preserves_old_data(tmp_path):
    path = tmp_path / "old-only.sqlite"
    migrate(path, "upgrade", "0018_tp025b")
    with sqlite3.connect(path) as db:
        old_id = write_audit(db, "TASK", "TASK_CAPTURED")
    migrate(path, "upgrade", "head")
    migrate(path, "downgrade", "0018_tp025b")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT entity_type FROM history_events WHERE entity_id=?",
                          (old_id,)).fetchone() == ("TASK",)
        with pytest.raises(sqlite3.IntegrityError):
            write_audit(db, "ELIGIBILITY_SERIES", "ELIGIBILITY_SERIES_CHANGED")
    migrate(path, "upgrade", "head")
