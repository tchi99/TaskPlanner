import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _upgrade(path: Path, revision: str, *, check: bool = True):
    env = os.environ.copy()
    env["TASKPLANNER_DATABASE_URL"] = _database_url(path)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def test_migration_from_0001_preserves_existing_capture_without_fake_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "migration.db"
    task_id = str(uuid4())
    _upgrade(database, "0001_tasks")

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                id, title, project_id, notes, status, protection,
                work_type_id, estimated_minutes, due_at, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                task_id,
                "Legacy capture",
                "Legacy notes",
                "INBOX",
                "REPLANNABLE",
                45,
                "2026-09-28 13:00:00.000000",
                "2026-09-27 14:00:00.000000",
            ),
        )
        connection.commit()

    _upgrade(database, "head")

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT id, title, notes, status, protection, estimated_minutes,
                   due_at, created_at
            FROM tasks WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        history_count = connection.execute(
            "SELECT COUNT(*) FROM history_events"
        ).fetchone()[0]
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert row == (
        task_id,
        "Legacy capture",
        "Legacy notes",
        "INBOX",
        "REPLANNABLE",
        45,
        "2026-09-28 13:00:00.000000",
        "2026-09-27 14:00:00.000000",
    )
    assert history_count == 0
    assert {"projects", "work_types", "task_segments", "history_events"} <= tables


def test_migration_fails_clearly_instead_of_inventing_missing_reference(
    tmp_path: Path,
) -> None:
    database = tmp_path / "orphan.db"
    task_id = str(uuid4())
    project_id = str(uuid4())
    _upgrade(database, "0001_tasks")

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                id, title, project_id, notes, status, protection,
                work_type_id, estimated_minutes, due_at, created_at
            ) VALUES (?, ?, ?, NULL, 'INBOX', 'REPLANNABLE', NULL, NULL, NULL, ?)
            """,
            (task_id, "Orphan", project_id, "2026-09-27 14:00:00.000000"),
        )
        connection.commit()

    result = _upgrade(database, "head", check=False)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "Cannot migrate tasks.project_id" in output
    assert task_id in output
    assert project_id in output
