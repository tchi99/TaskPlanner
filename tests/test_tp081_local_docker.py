"""TP-081: guardrails for the LOCAL-only Docker Compose test environment."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_configuration_does_not_publish_private_services() -> None:
    config = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "name: taskplanner-local" in config
    assert config.count("\n    ports:\n") == 1
    assert '      - "127.0.0.1:5173:5173"' in config
    assert "taskplanner_pg_data:/var/lib/postgresql/data" in config
    assert "condition: service_completed_successfully" in config
    assert 'command: ["alembic", "upgrade", "head"]' in config
    assert "pg_isready -h 127.0.0.1" in config
    assert "VITE_TASKPLANNER_AUTH_MODE: local" in config
    assert "TASKPLANNER_AUTH_MODE: local" in config
    assert "TASKPLANNER_ENV: test" in config
    assert "sslmode=disable" in config
    assert "TASKPLANNER_VITE_API_PROXY_TARGET: http://backend:8000" in config
    assert "VITE_SUPABASE_PUBLISHABLE_KEY" not in config
    assert "TASKPLANNER_SUPABASE_ALLOWED_SUB" not in config


def test_docker_assets_and_local_auth_boundaries_exist() -> None:
    for path in (
        "docker/backend.Dockerfile",
        "docker/frontend.dev.Dockerfile",
        "docker/init/01-create-schema.sql",
        "docker/.env.example",
        ".dockerignore",
        "docs/LOCAL_DOCKER.md",
    ):
        assert (ROOT / path).is_file(), path

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "\n.env\n" in dockerignore
    assert "**/node_modules" in dockerignore

    vite_config = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    assert 'process.env.TASKPLANNER_VITE_API_PROXY_TARGET || "http://localhost:8000"' in vite_config

    auth = (ROOT / "frontend/src/auth.ts").read_text(encoding="utf-8")
    assert "import.meta.env.DEV &&" in auth
