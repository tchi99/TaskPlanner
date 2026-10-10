"""TP-080D safety gates must reject remote or non-disposable databases."""
import os
from unittest.mock import patch

import pytest

from scripts.verify_disposable_restore import (
    DrillError, connection_params, process_env, run_drill, validate_test_url,
)


@pytest.mark.parametrize("url", [
    None,
    "",
    "sqlite:///./taskplanner.db",
    "postgresql+psycopg://user:pw@db.supabase.co:5432/taskplanner_test",
    "postgresql+psycopg://user:pw@127.0.0.1:5432/taskplanner",
    "postgresql+psycopg://user:pw@127.0.0.1:5432/postgres",
    "postgresql://user:pw@localhost:5432/taskplanner_test",
    "postgresql+psycopg://user:pw@127.0.0.1:5432/taskplanner_test?sslmode=prefer",
])
def test_remote_or_non_disposable_targets_rejected(url):
    with pytest.raises(DrillError):
        validate_test_url(url)


def test_rejected_url_does_not_call_postgres_or_subprocess():
    with patch("scripts.verify_disposable_restore.psycopg.connect") as connect:
        with patch("scripts.verify_disposable_restore.subprocess.run") as run:
            with pytest.raises(DrillError):
                run_drill(
                    "postgresql+psycopg://user:secret@db.supabase.co:5432/taskplanner_test"
                )
            connect.assert_not_called()
            run.assert_not_called()


def test_password_is_not_a_command_argument_or_console_value(monkeypatch):
    monkeypatch.setenv("TASKPLANNER_PG_TEST_URL", "sensitive-dsn-must-not-be-inherited")
    url = validate_test_url(
        "postgresql+psycopg://user:private-password@localhost/taskplanner_test?sslmode=disable"
    )
    env = process_env(url)
    assert env["PGPASSWORD"] == "private-password"
    assert "TASKPLANNER_PG_TEST_URL" not in env
    assert connection_params(url, "taskplanner_restore_test_123")["dbname"] == \
        "taskplanner_restore_test_123"
    assert "private-password" not in env["PGDATABASE"]
    assert not any("private-password" in value for key, value in env.items()
                   if key != "PGPASSWORD")
