"""TP-024A additive migration: SQLite legacy data remain intact and downgrade guards."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, revision, action="upgrade", *, succeed=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )
    if succeed:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0, "unsafe downgrade unexpectedly succeeded"
    return result


def test_tp024a_retains_legacy_rows_without_guessed_parent(tmp_path):
    path = tmp_path / "migration.sqlite"
    migrate(path, "0015_tp023a")
    wid = str(uuid4())
    rid = str(uuid4())
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO work_types(id,name,description) VALUES (?,?,NULL)",
                   (wid, "Travail"))
        db.execute(
            "INSERT INTO recurring_availability_rules"
            " (id,owner_id,version,created_at) VALUES (?,?,1,?)",
            (rid, "urn:taskplanner:local", "2026-10-15T00:00:00Z"),
        )
        db.execute(
            "INSERT INTO recurring_availability_revisions"
            " (id,rule_id,number,effective_from,valid_until,timezone_name,"
            "days_of_week,starts_at_local,ends_at_local,kind,work_type_id,"
            "mode,enabled,start_fold,end_fold,recorded_at,supersedes_future)"
            " VALUES (?,?,1,'2027-01-01',NULL,'America/Toronto','[1]',"
            "'09:00','10:00','CATEGORIZED',?,'PREFERRED',1,NULL,NULL,?,0)",
            (str(uuid4()), rid, wid, "2026-10-15T00:00:00Z"),
        )
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0016_tp024a",
        )
        assert db.execute(
            "SELECT work_type_id, scope_id FROM recurring_availability_revisions "
            "WHERE rule_id=?", (rid,),
        ).fetchone() == (wid, None)
        assert db.execute(
            "SELECT name FROM work_types WHERE id=?", (wid,),
        ).fetchone() == ("Travail",)
        assert db.execute("SELECT COUNT(*) FROM schedule_scopes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM work_type_scope_assignments").fetchone()[0] == 0
        assert "scope_id" in {
            row[1] for row in db.execute("PRAGMA table_info(confirmed_time_blocks)")
        }
    migrate(path, "0015_tp023a", "downgrade")
    with sqlite3.connect(path) as db:
        assert "scope_id" not in {
            row[1] for row in db.execute(
                "PRAGMA table_info(recurring_availability_revisions)"
            )
        }
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO schedule_scopes"
            " (id,owner_id,name,state,version,is_compatibility)"
            " VALUES (?,?,'Travail','ACTIVE',1,0)",
            (str(uuid4()), "urn:taskplanner:local"),
        )
    migrate(path, "0015_tp023a", "downgrade", succeed=False)
