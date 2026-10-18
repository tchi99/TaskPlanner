"""TP-026A scope/API regressions after removal of historical affiliations.

The dated affiliation/compatibility tests previously in this module tested a
superseded persistence contract. Their new equivalents assert permanent direct
WorkType.scope_id parentage, owner checks, CAS and atomic parent envelopes.
The full legacy endpoint retirement belongs to TP-026C.
"""
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import WorkTypeRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app

ZONE = "America/Toronto"
ROOT = "/api/schedule-scopes"
GRID = "/api/availability/weekly-schedule"


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scopes.sqlite'}",
                           connect_args={"check_same_thread": False, "timeout": 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_empty_install_and_direct_parented_leaf(runtime):
    client, factory = runtime
    assert client.get(ROOT).json() == {"scopes": []}
    assert client.get("/api/work-types").json() == []
    assert client.post("/api/work-types", json={"name": "Unparented"}).status_code == 422
    parent_response = client.post(ROOT, json={"name": "Travail"})
    assert parent_response.status_code == 201, parent_response.text
    parent = parent_response.json()
    assert client.post(ROOT, json={"name": "travail"}).status_code == 409
    leaf = client.post("/api/work-types", json={
        "name": "Focus", "scope_id": parent["id"]})
    assert leaf.status_code == 201, leaf.text
    assert leaf.json()["scope_id"] == parent["id"]
    assert leaf.json()["version"] == 1
    with factory() as session:
        assert session.scalar(select(WorkTypeRecord)).scope_id == parent["id"]


def test_scope_rename_preserves_leaf_and_scope_cas(runtime):
    client, factory = runtime
    parent = client.post(ROOT, json={"name": "Travail"}).json()
    leaf = client.post("/api/work-types", json={
        "name": "Réunions", "scope_id": parent["id"]}).json()
    changed = client.patch(f'{ROOT}/{parent["id"]}', json={
        "name": "Professionnel", "expected_version": 1, "state": "ACTIVE"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert changed.json()["id"] == parent["id"]
    stale = client.patch(f'{ROOT}/{parent["id"]}', json={
        "name": "Périmé", "expected_version": 1, "state": "ACTIVE"})
    assert stale.status_code == 409
    assert client.get("/api/work-types").json()[0]["scope_id"] == parent["id"]
    assert client.patch(f'/api/work-types/{leaf["id"]}', json={
        "name": "Tentative de transfert", "expected_version": 1,
        "scope_id": str(uuid4())}).status_code == 422


def test_parent_cannot_be_deactivated_with_leaf_or_unknown_parent(runtime):
    client, factory = runtime
    scope = client.post(ROOT, json={"name": "Personnel"}).json()["id"]
    assert client.post("/api/work-types", json={
        "name": "Orpheline", "scope_id": str(uuid4())}).status_code == 422
    leaf = client.post("/api/work-types", json={
        "name": "Maison", "scope_id": scope})
    assert leaf.status_code == 201, leaf.text
    inactive = client.patch(f"{ROOT}/{scope}", json={
        "name": "Personnel", "state": "INACTIVE", "expected_version": 1})
    assert inactive.status_code == 409
    assert client.get(ROOT).json()["scopes"][0]["state"] == "ACTIVE"


def test_weekly_parent_envelope_uses_real_scope_and_atomic_confirm(runtime):
    client, factory = runtime
    parent = client.post(ROOT, json={"name": "Travail"}).json()["id"]
    tomorrow = datetime.now(ZoneInfo(ZONE)).date() + timedelta(days=21)
    payload = {
        "effective_from": str(tomorrow), "timezone_name": ZONE,
        "sections": [{
            "weekday": tomorrow.weekday(), "kind": "GENERAL", "scope_id": parent,
            "work_type_id": None,
            "slots": [{"starts_at_local": "09:00", "ends_at_local": "12:00"}],
        }],
        "expected_versions": {},
    }
    preview = client.post(GRID + "/preview", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["has_changes"]
    confirmed = client.post(GRID + "/confirm", json={
        **payload, "fingerprint": preview.json()["fingerprint"],
        "command_id": str(uuid4()), "confirmed": True,
    })
    assert confirmed.status_code == 200, confirmed.text
    with SqlAlchemyUnitOfWork(factory) as uow:
        rules = tuple(uow.recurring_availability.list_owner("urn:taskplanner:local"))
        assert rules and all(rev.scope_id == __import__("uuid").UUID(parent)
                             for rule in rules for rev in rule.revisions)
