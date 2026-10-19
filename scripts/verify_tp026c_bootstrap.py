"""TP-026C: CI-only fresh-local Docker bootstrap through the actual Vite API proxy.

This script never resets, migrates or connects directly to a database. It
creates test data, so run it only against a verified disposable, EMPTY local
Compose instance. Host is deliberately fixed to loopback; no credentials used.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:5173"
ZONE = "America/Toronto"


def request(method: str, path: str, payload: dict | None = None, expected: int = 200):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE + path, data=body, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as response:
            code = response.status
            result = response.read()
    except HTTPError as exc:
        code, result = exc.code, b""
    if code != expected:
        raise AssertionError(f"{method} {path.split('?')[0]}: expected {expected}, got {code}")
    return json.loads(result) if result else None


def main() -> None:
    request("GET", "/api/health")
    scopes = request("GET", "/api/schedule-scopes")
    assert scopes["scopes"] == [], "The fresh database pre-created parent scopes"
    assert request("GET", "/api/work-types") == []
    assert request("GET", "/api/availability/rules") == []
    assert request("GET", "/api/availability/exceptions") == []
    assert request("POST", "/api/availability/rules", {}, expected=405) is None
    assert request("POST", "/api/capacity/weeks/2027-01-04/blocks",
                   {}, expected=404) is None

    today = datetime.now(ZoneInfo(ZONE)).date()
    effect = today + timedelta(days=((7 - today.weekday()) % 7) + 14)
    scope_response = request("POST", "/api/schedule-scopes", {"name": "Travail"}, 201)
    scope = scope_response["id"]
    names = []
    for name in ("Focus", "Réunions"):
        leaf = request("POST", "/api/work-types", {
            "name": name, "scope_id": scope,
        }, 201)
        assert leaf["scope_id"] == scope
        names.append(leaf["id"])
    envelope = {
        "effective_from": effect.isoformat(), "timezone_name": ZONE,
        "sections": [{
            "weekday": 0, "kind": "GENERAL", "scope_id": scope,
            "work_type_id": None,
            "slots": [{"starts_at_local": "09:00", "ends_at_local": "11:00"}],
        }], "expected_versions": {},
    }
    offer = request("POST", "/api/availability/weekly-schedule/preview", envelope)
    assert offer["has_changes"]
    receipt = request("POST", "/api/availability/weekly-schedule/confirm", {
        **envelope, "fingerprint": offer["fingerprint"],
        "command_id": str(uuid4()), "confirmed": True,
    })
    assert receipt["applied"]
    for typ, rank in zip(names, (1, 2)):
        draft = {
            "draft_id": str(uuid4()), "series_id": None,
            "scope_id": scope, "work_type_id": typ, "expected_version": 0,
            "effective_from": effect.isoformat(), "timezone_name": ZONE,
            "days_of_week": [0], "starts_at_local": "09:00",
            "ends_at_local": "11:00", "priority_rank": rank, "enabled": True,
        }
        preview = request("POST", "/api/availability/eligibility-edits/preview", draft)
        assert preview["blocking_issues"] == [], preview["blocking_issues"]
        assert preview["before_physical_minutes"] == preview["after_physical_minutes"]
        saved = request("POST", "/api/availability/eligibility-edits/confirm", {
            **draft, "command_id": str(uuid4()),
            "fingerprint": preview["fingerprint"], "confirmed": True,
        })
        assert saved["applied"] and saved["calendar_written"] is False
    from urllib.parse import urlencode
    query = urlencode({"week_start": effect.isoformat(), "timezone_name": ZONE})
    rendered = request("GET", "/api/availability/eligibility-week?" + query)
    assert rendered["physical_minutes"] == 120, rendered["physical_minutes"]
    assert sorted(item["minutes"] for item in rendered["potential_minutes"]) == [120, 120]
    assert any(len(item["choices"]) == 2 for item in rendered["fragments"])
    print("TP-026C fresh Docker bootstrap: VERIFIED (single physical capacity, two permissions)")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, URLError, ValueError):
        # Never print response bodies or environment; no secrets in output.
        print("TP-026C fresh Docker bootstrap: FAILED")
        raise SystemExit(1)
