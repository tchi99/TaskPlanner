"""TP-023A preserves legacy recurring revisions and supports same-date records."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def migrate(path, revision, action="upgrade", *, succeed=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=ROOT, check=False, capture_output=True, text=True,
        env={**os.environ, "TASKPLANNER_DATABASE_URL": f"sqlite:///{path}"},
    )
    if succeed:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    return result


def test_legacy_revisions_preserved_same_date_and_downgrade_guard(tmp_path):
    path = tmp_path / "legacy.sqlite"
    migrate(path, "0014_tp022r")
    rid = str(uuid4())
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO recurring_availability_rules "
            "(id,owner_id,version,created_at) VALUES (?,?,1,?)",
            (rid, "migration-owner", "2026-10-14T12:00:00Z"),
        )
        db.execute(
            "INSERT INTO recurring_availability_revisions "
            "(id, rule_id, number, effective_from, valid_until, timezone_name,"
            "days_of_week, starts_at_local, ends_at_local, kind, work_type_id,"
            "mode, enabled, start_fold, end_fold, recorded_at) "
            "VALUES (?,?,1,'2027-01-01',NULL,'America/Toronto','[1]',"
            "'09:00','10:00','GENERAL',NULL,NULL,1,NULL,NULL,?)",
            (str(uuid4()), rid, "2026-10-14T12:00:00Z"),
        )
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0017_tp025a",
        )
        assert db.execute(
            "SELECT number, effective_from, supersedes_future "
            "FROM recurring_availability_revisions WHERE rule_id=?", (rid,),
        ).fetchall() == [(1, "2027-01-01", 0)]
        assert "weekly_schedule_commands" in {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        db.execute(
            "UPDATE recurring_availability_rules SET version=2 WHERE id=?", (rid,),
        )
        db.execute(
            "INSERT INTO recurring_availability_revisions "
            "(id, rule_id, number, effective_from, valid_until, timezone_name,"
            "days_of_week, starts_at_local, ends_at_local, kind, work_type_id,"
            "mode, enabled, start_fold, end_fold, recorded_at, supersedes_future) "
            "VALUES (?,?,2,'2027-01-01',NULL,'America/Toronto','[1]',"
            "'09:00','10:00','GENERAL',NULL,NULL,0,NULL,NULL,?,1)",
            (str(uuid4()), rid, "2026-10-15T12:00:00Z"),
        )
        assert db.execute(
            "SELECT COUNT(*) FROM recurring_availability_revisions "
            "WHERE rule_id=? AND effective_from='2027-01-01'", (rid,),
        ).fetchone()[0] == 2
    migrate(path, "0014_tp022r", "downgrade", succeed=False)


def test_tp024a_upgrade_preserves_tp023a_and_blocks_unsafe_downgrade(tmp_path):
    path = tmp_path / "empty.sqlite"
    migrate(path, "head")
    migrate(path, "0015_tp023a", "downgrade")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0015_tp023a",
        )
        assert "scope_id" not in {
            row[1] for row in db.execute(
                "PRAGMA table_info(recurring_availability_revisions)"
            )
        }
    migrate(path, "head")
