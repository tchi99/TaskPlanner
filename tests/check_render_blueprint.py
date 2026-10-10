"""Offline structural checks for the unactivated TP-080C Render Blueprint."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
data = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
assert data["previews"]["generation"] == "off"
services = {service["name"]: service for service in data["services"]}
assert set(services) == {"taskplanner-api", "taskplanner-web"}
api, web = services["taskplanner-api"], services["taskplanner-web"]

for service in (api, web):
    assert service["type"] == "web"
    assert service["autoDeployTrigger"] == "off"
    assert service["branch"] == "main"
    assert "preDeployCommand" not in service  # migrations need explicit controlled execution
    assert "initialDeployHook" not in service
    assert service.get("previews", {}).get("generation") != "automatic"

assert api["runtime"] == "python"
assert api["plan"] == "free"
assert api["healthCheckPath"] == "/api/health"
assert "uvicorn app.main:app" in api["startCommand"]
assert "--host 0.0.0.0 --port $PORT" in api["startCommand"]
assert "--no-access-log" in api["startCommand"]
assert api["buildCommand"] == "pip install -r requirements.txt"

assert web["runtime"] == "static"
assert web["rootDir"] == "frontend"
assert web["staticPublishPath"] == "./dist"
assert "npm ci" in web["buildCommand"] and "npm run build" in web["buildCommand"]
assert web["routes"] == [{"type": "rewrite", "source": "/*", "destination": "/index.html"}]
assert any(h["name"] == "X-Content-Type-Options" for h in web["headers"])

api_vars = {item["key"]: item for item in api["envVars"]}
web_vars = {item["key"]: item for item in web["envVars"]}
assert {"TASKPLANNER_DATABASE_URL", "TASKPLANNER_SUPABASE_URL",
        "TASKPLANNER_SUPABASE_ALLOWED_SUB", "TASKPLANNER_CORS_ORIGINS"} <= api_vars.keys()
for key in ("TASKPLANNER_DATABASE_URL", "TASKPLANNER_SUPABASE_URL",
            "TASKPLANNER_SUPABASE_ALLOWED_SUB", "TASKPLANNER_CORS_ORIGINS"):
    assert api_vars[key] == {"key": key, "sync": False}
assert api_vars["TASKPLANNER_ENV"]["value"] == "production"
assert api_vars["TASKPLANNER_AUTH_MODE"]["value"] == "supabase"
assert api_vars["TASKPLANNER_DATABASE_SCHEMA"]["value"] == "taskplanner"
assert all(not key.startswith("VITE_") for key in api_vars)
assert {"VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY",
        "VITE_TASKPLANNER_API_URL"} <= web_vars.keys()
assert all(item.get("sync") is False for key, item in web_vars.items() if key.startswith("VITE_"))
assert all("SECRET" not in key and "PASSWORD" not in key and "DATABASE" not in key
           and "SERVICE_ROLE" not in key and "PRIVATE" not in key for key in web_vars)
assert "databases" not in data  # database is provisioned separately in Supabase
print("TP-080C Render Blueprint policy: OK")
