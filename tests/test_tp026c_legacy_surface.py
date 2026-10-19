"""TP-026C: obsolete write contracts cannot be used on a fresh installation."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import app
from app.server.eligibility_edits import DraftInput


def test_legacy_mutation_routes_are_absent_but_read_contracts_survive():
    routes = {(method, route.path) for route in app.routes
              for method in (getattr(route, "methods", None) or set())}
    assert ("POST", "/api/capacity/weeks/{week_start}/blocks") not in routes
    assert ("DELETE", "/api/capacity/weeks/{week_start}/blocks/{block_id}") not in routes
    assert ("POST", "/api/availability/rules") not in routes
    assert ("PATCH", "/api/availability/rules/{rule_id}") not in routes
    assert ("DELETE", "/api/availability/rules/{rule_id}") not in routes
    assert ("GET", "/api/availability/rules") in routes
    assert ("GET", "/api/availability/rules/occurrences") in routes
    assert ("POST", "/api/availability/weekly-schedule/preview") in routes
    assert ("POST", "/api/availability/weekly-schedule/confirm") in routes
    assert ("POST", "/api/availability/eligibility-edits/confirm") in routes
    assert ("POST", "/api/capacity/weeks/{week_start}/evaluate") in routes


@pytest.mark.parametrize("obsolete", ["legacy_rule_id", "expected_legacy_version"])
def test_draft_rejects_deleted_cutover_fields_explicitly(obsolete):
    payload = {
        "draft_id": str(uuid4()), "series_id": None,
        "scope_id": str(uuid4()), "work_type_id": str(uuid4()),
        "expected_version": 0, "effective_from": "2027-01-11",
        "timezone_name": "America/Toronto", "days_of_week": [0],
        "starts_at_local": "09:00", "ends_at_local": "11:00",
        "priority_rank": None, "enabled": True,
        obsolete: None,
    }
    with pytest.raises(ValidationError, match=obsolete):
        DraftInput.model_validate(payload)
