"""TP-025A SQLite upgrade is additive and downgrade must not destroy history."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, command, revision, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )
    assert (result.returncode == 0) == success, result.stderr
    return result


def test_additive_upgrade_and_guarded_downgrade(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    migrate(db_path, "upgrade", "0016_tp024a")
    identity = str(uuid4())
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO work_types(id,name,description) VALUES (?,?,NULL)",
                   (identity, "Existing",))
    migrate(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0019_tp025d"
        assert db.execute("SELECT name FROM work_types WHERE id=?", (identity,)).fetchone() == ("Existing",)
        assert db.execute("SELECT COUNT(*) FROM eligibility_series").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM recurring_availability_rules").fetchone()[0] == 0
        assert any(row[2] == "schedule_scopes" and row[6] == "RESTRICT"
                   for row in db.execute("PRAGMA foreign_key_list(eligibility_series)"))
    migrate(db_path, "downgrade", "0016_tp024a")
    migrate(db_path, "upgrade", "head")
    with sqlite3.connect(db_path) as db:
        scope, sid = str(uuid4()), str(uuid4())
        db.execute("INSERT INTO schedule_scopes"
                   "(id, owner_id, name, state, version, is_compatibility)"
                   "VALUES (?, 'owner', 'Travail', 'ACTIVE', 1, 0)", (scope,))
        db.execute("INSERT INTO eligibility_series"
                   "(id, owner_id, scope_id, work_type_id, version, created_at)"
                   "VALUES (?, 'owner', ?, ?, 1, '2027-01-01T00:00:00Z')",
                   (sid, scope, identity))
    migrate(db_path, "downgrade", "0016_tp024a", success=False)
