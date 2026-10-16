"""TP-024A scope contract and disjoint UTC projection on SQLite.

No actual production migrations, GitHub side effects or Google calendar writes.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.domain.schedule_scopes import compatibility_scope_id, effective_scope
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import (
    ScopeChangeCommandRecord, ScopeChangeAuditRecord,
    WorkTypeScopeAssignmentRecord, RecurringAvailabilityRevisionRecord,
)
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


def monday():
    today = datetime.now(ZoneInfo(ZONE)).date()
    return today + timedelta(days=14 + (7 - today.weekday()) % 7)


def make_scope(client, name):
    response = client.post(ROOT, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def leaf(client, name="Focus"):
    response = client.post("/api/work-types", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def draft_affiliation(work_type_id, scope, day, version=0):
    return {
        "work_type_id": work_type_id, "scope_id": scope["id"],
        "effective_from": str(day), "timezone_name": ZONE,
        "expected_affiliation_version": version,
        "expected_scope_version": scope["version"],
    }


def preview_affiliation(client, body):
    result = client.post(ROOT + "/affiliations/preview", json=body)
    assert result.status_code == 200, result.text
    return result.json()


def confirm_affiliation(client, body, token, command=None, **kwargs):
    return client.post(ROOT + "/affiliations/confirm", json={
        **body, "command_id": str(command or uuid4()),
        "fingerprint": token["fingerprint"], "confirmed": True, **kwargs,
    })


def schedule(client, day, scope, weekday, kind, begin, end, *, type_id=None,
             mode=None, confirmed=True):
    input_ = {
        "effective_from": str(day), "timezone_name": ZONE,
        "sections": [{
            "weekday": weekday, "kind": kind, "scope_id": scope["id"],
            "work_type_id": type_id,
            "slots": [{"starts_at_local": begin, "ends_at_local": end,
                       **({"mode": mode} if mode else {})}],
        }],
        "expected_versions": {},
    }
    preview = client.post(GRID + "/preview", json=input_)
    assert preview.status_code == 200, preview.text
    token = preview.json()
    if not confirmed:
        return input_, token
    saved = client.post(GRID + "/confirm", json={
        **input_, "fingerprint": token["fingerprint"], "command_id": str(uuid4()),
        "confirmed": True,
    })
    assert saved.status_code == 200, saved.text
    return input_, token


def projection(client, day):
    response = client.get("/api/availability/effective", params={
        "from": str(day), "to": str(day + timedelta(days=7)), "timezone_name": ZONE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_owner_scopes_leaf_identity_temporal_affiliation_and_idempotence(runtime):
    client, factory = runtime
    initial = client.get(ROOT).json()
    assert len(initial["scopes"]) == 1
    assert initial["scopes"][0]["is_compatibility"]
    assert initial["scopes"][0]["id"] == str(compatibility_scope_id("urn:taskplanner:local"))
    work = make_scope(client, "Travail")
    personal = make_scope(client, "Personnel")
    work_type = leaf(client, "Travail")
    assert client.post(ROOT, json={"name": "travail"}).status_code == 409
    effect = monday()
    body = draft_affiliation(work_type, work, effect)
    token = preview_affiliation(client, body)
    assert token["from_scope_id"] == initial["compatibility_scope_id"]
    command = uuid4()
    stored = confirm_affiliation(client, body, token, command=command)
    assert stored.status_code == 200, stored.text
    replay = confirm_affiliation(client, body, token, command=command)
    assert replay.status_code == 200 and replay.json() == stored.json()
    assert UUID(work_type) in [UUID(row["id"]) for row in
                               client.get("/api/work-types").json()]
    move = draft_affiliation(work_type, personal, effect + timedelta(days=7), 1)
    token2 = preview_affiliation(client, move)
    changed = confirm_affiliation(client, move, token2)
    assert changed.status_code == 200, changed.text
    state = client.get(ROOT).json()
    attached = tuple(
        type("A", (), {"work_type_id": UUID(x["work_type_id"]),
                        "scope_id": UUID(x["scope_id"]),
                        "effective_from": datetime.fromisoformat(x["effective_from"]).date(),
                        "version": x["version"]})
        for x in state["affiliations"]
    )
    compat = UUID(state["compatibility_scope_id"])
    assert effective_scope(UUID(work_type), effect-timedelta(days=1), attached, compat) == compat
    assert effective_scope(UUID(work_type), effect, attached, compat) == UUID(work["id"])
    assert effective_scope(UUID(work_type), effect+timedelta(days=7), attached, compat) == UUID(personal["id"])
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkTypeScopeAssignmentRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ScopeChangeCommandRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ScopeChangeAuditRecord)) >= 4


def test_stale_scope_version_and_affiliation_return_409_no_partial_writes(runtime):
    client, factory = runtime
    work = make_scope(client, "Travail")
    one = leaf(client)
    body = draft_affiliation(one, work, monday())
    token = preview_affiliation(client, body)
    rename = client.patch(ROOT + "/" + work["id"], json={
        "name": "Travail renommé", "state": "ACTIVE", "expected_version": 1})
    assert rename.status_code == 200, rename.text
    stale = confirm_affiliation(client, body, token)
    assert stale.status_code == 409, stale.text
    corrected = {**body, "expected_scope_version": 2}
    fresh = preview_affiliation(client, corrected)
    assert confirm_affiliation(client, corrected, fresh).status_code == 200
    other = make_scope(client, "Personnel")
    followup = draft_affiliation(one, other, monday() + timedelta(days=7), 1)
    duplicated = preview_affiliation(client, followup)
    assert confirm_affiliation(client, followup, duplicated).status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkTypeScopeAssignmentRecord)) == 2


def test_two_parent_null_buckets_and_cross_parent_overlap_is_never_counted(runtime):
    client, _ = runtime
    work = make_scope(client, "Travail")
    personal = make_scope(client, "Personnel")
    effect = monday()
    schedule(client, effect, work, 0, "GENERAL", "09:00", "10:00")
    schedule(client, effect, personal, 1, "GENERAL", "09:00", "10:00")
    result = projection(client, effect)
    nulls = [b for b in result["blocks"] if b["work_type_id"] is None]
    assert {b["scope_id"] for b in nulls} == {work["id"], personal["id"]}
    assert result["declared_minutes"] == 120
    # Both different parents try to claim the very same physical minute.
    body, token = schedule(client, effect, personal, 0, "GENERAL",
                           "09:30", "10:00", confirmed=False)
    assert "INCOMPATIBLE_SCOPES" in token["invalid_conflicts"]
    assert any(r["code"] == "INCOMPATIBLE_SCOPES" and r["status"] == "NEW"
               for r in token["invalid_diagnostics"])
    refused = client.post(GRID + "/confirm", json={
        **body, "fingerprint": token["fingerprint"],
        "command_id": str(uuid4()), "confirmed": True,
    })
    assert refused.status_code == 422
    assert projection(client, effect)["declared_minutes"] == 120


def test_scoped_category_and_cancel_do_not_refill_parent_null(runtime):
    client, _ = runtime
    work = make_scope(client, "Travail")
    work_type = leaf(client)
    effect = monday()
    body = draft_affiliation(work_type, work, effect)
    token = preview_affiliation(client, body)
    assert confirm_affiliation(client, body, token).status_code == 200
    schedule(client, effect, work, 1, "GENERAL", "09:00", "11:00")
    schedule(client, effect, work, 1, "CATEGORIZED", "09:00", "10:00",
             type_id=work_type, mode="PREFERRED")
    before = projection(client, effect)
    assert before["declared_minutes"] == 120
    assert sum(b["minutes"] for b in before["blocks"]
               if b["work_type_id"] == work_type) == 60
    grid = client.get(GRID, params={
        "effective_from": str(effect), "timezone_name": ZONE,
        "scope_id": work["id"],
    }).json()
    classified = next(s for s in grid["sections"] if s["kind"] == "CATEGORIZED")
    rule_id = classified["slots"][0]["sources"][0]["rule_id"]
    exception = {
        "action": "CANCEL", "rule_id": rule_id,
        "original_local_date": str(effect + timedelta(days=1)),
        "timezone_name": ZONE, "scope_id": work["id"],
    }
    preview = client.post("/api/availability/exceptions/preview", json=exception)
    assert preview.status_code == 200, preview.text
    saved = client.post("/api/availability/exceptions", json={
        **exception, "expected_fingerprint": preview.json()["fingerprint"],
    })
    assert saved.status_code == 201, saved.text
    after = projection(client, effect)
    # One occurrence is cancelled; other Tuesdays remain within the 7d window.
    assert after["declared_minutes"] == 60
    assert all(not (b["work_type_id"] is None
                    and b["starts_at"].startswith(str(effect+timedelta(days=1)))
                    and b["minutes"] > 60) for b in after["blocks"])


def test_scoped_global_unavailability_and_compatibility_are_distinct(runtime):
    client, _ = runtime
    work = make_scope(client, "Travail")
    personal = make_scope(client, "Personnel")
    effect = monday()
    schedule(client, effect, work, 0, "GENERAL", "09:00", "10:00")
    schedule(client, effect, personal, 1, "GENERAL", "09:00", "10:00")
    day = effect + timedelta(days=1)
    start = datetime.combine(day, datetime.min.time(), ZoneInfo(ZONE)).replace(hour=9)
    end = start + timedelta(minutes=30)
    exc = {
        "action": "UNAVAILABLE", "timezone_name": ZONE,
        "starts_at": start.isoformat(), "ends_at": end.isoformat(),
        "scope_id": personal["id"],
    }
    prev = client.post("/api/availability/exceptions/preview", json=exc)
    assert prev.status_code == 200, prev.text
    saved = client.post("/api/availability/exceptions", json={
        **exc, "expected_fingerprint": prev.json()["fingerprint"],
    })
    assert saved.status_code == 201, saved.text
    after = projection(client, effect)
    assert after["declared_minutes"] == 90
    assert any(i["code"] == "DECLARED_UNAVAILABLE" and
               personal["id"] in i["scope_ids"] for i in after["issues"])


def test_competing_affiliation_confirmations_one_wins_sqlite(runtime):
    client, factory = runtime
    first = make_scope(client, "Travail")
    second = make_scope(client, "Personnel")
    work_type = leaf(client)
    day = monday()
    choices = [draft_affiliation(work_type, scope, day) for scope in (first, second)]
    tokens = [preview_affiliation(client, x) for x in choices]
    def submit(choice):
        index, body = choice
        return confirm_affiliation(client, body, tokens[index]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit, enumerate(choices)))
    assert sorted(statuses) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkTypeScopeAssignmentRecord)) == 1


# TP-024C: integration regressions of parent identity and legacy API scope.
def test_tp024c_legacy_weekly_endpoint_cannot_aggregate_parent_envelopes(runtime):
    client, _ = runtime
    work = make_scope(client, "Travail")
    personal = make_scope(client, "Personnel")
    day = monday()
    schedule(client, day, work, 0, "GENERAL", "09:00", "11:00")
    schedule(client, day, personal, 1, "GENERAL", "13:00", "15:00")
    legacy = client.get(GRID, params={
        "effective_from": str(day), "timezone_name": ZONE,
    })
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["scope_id"] is None
    assert legacy.json()["sections"] == []
    for parent in (work, personal):
        scoped = client.get(GRID, params={
            "effective_from": str(day), "timezone_name": ZONE,
            "scope_id": parent["id"],
        })
        assert scoped.status_code == 200, scoped.text
        assert len(scoped.json()["sections"]) == 1
        assert scoped.json()["sections"][0]["scope_id"] == parent["id"]
    assert projection(client, day)["declared_minutes"] == 240


def test_tp024c_parent_rename_preserves_leaf_membership_and_physical_capacity(runtime):
    client, _ = runtime
    work = make_scope(client, "Travail")
    child = leaf(client, "Gestion")
    day = monday()
    draft = draft_affiliation(child, work, day)
    token = preview_affiliation(client, draft)
    assert confirm_affiliation(client, draft, token).status_code == 200
    schedule(client, day, work, 0, "GENERAL", "09:00", "11:00")
    schedule(client, day, work, 0, "CATEGORIZED", "09:00", "10:00",
             type_id=child, mode="PROTECTED")
    before = projection(client, day)
    assert before["declared_minutes"] == 120
    assert sum(b["minutes"] for b in before["blocks"]
               if b["work_type_id"] == child) == 60
    renamed = client.patch(ROOT + "/" + work["id"], json={
        "name": "Bureau", "state": "ACTIVE",
        "expected_version": work["version"],
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["id"] == work["id"]
    assert renamed.json()["version"] == work["version"] + 1
    catalog = client.get(ROOT).json()
    assert any(row["work_type_id"] == child and row["scope_id"] == work["id"]
               for row in catalog["affiliations"])
    after = projection(client, day)
    assert after["declared_minutes"] == before["declared_minutes"]
    assert sorted((b["scope_id"], b["work_type_id"], b["minutes"])
                  for b in after["blocks"]) == sorted(
                      (b["scope_id"], b["work_type_id"], b["minutes"])
                      for b in before["blocks"])
