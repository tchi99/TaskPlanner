"""TP-070: suggested starts cannot mutate work; resume points are explicit and scoped."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, ResumePointRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def task(client, title="Analyser des données", clarify=True):
    response = client.post("/api/tasks", json={"title": title})
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    if clarify:
        response = client.post("/api/tasks/" + task_id + "/clarify", json={})
        assert response.status_code == 200, response.text
    return task_id


def assistance(client, task_id):
    return client.get("/api/tasks/" + task_id + "/start-assistance")


def save(client, task_id, snapshot, text, *, confirmed=True, revision=None):
    action = snapshot["next_action"]
    return client.put("/api/tasks/" + task_id + "/start-assistance/resume-point", json={
        "text": text,
        "target_id": action["target_id"],
        "action_type": action["action_type"],
        "expected_revision": snapshot["resume_revision"] if revision is None else revision,
        "confirmed": confirmed,
    })


def test_suggestion_is_temporary_and_next_action_remains_authoritative(setup):
    client, factory = setup
    task_id = task(client)
    before = client.get("/api/tasks/" + task_id + "/detail").json()
    with factory() as session:
        fact_count = len(session.scalars(select(HistoryEventRecord)).all())
    result = assistance(client, task_id)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["next_action"] == before["next_action"]
    assert value["starter_action"]["commitment_minutes"] == 10
    assert "première petite étape" in value["starter_action"]["text"]
    assert "BODY_DOUBLING" in {s["code"] for s in value["strategies"]}
    assert value["resume_point"] is None
    assert value["resume_revision"] == 0
    assert client.get("/api/tasks/" + task_id + "/detail").json() == before
    with factory() as session:
        assert session.scalars(select(ResumePointRecord)).all() == []
        assert len(session.scalars(select(HistoryEventRecord)).all()) == fact_count


def test_clarify_segment_review_and_terminal_actions(setup):
    client, _ = setup
    task_id = task(client, clarify=False)
    assert assistance(client, task_id).json()["next_action"]["action_type"] == "CLARIFY_TASK"
    assert assistance(client, task_id).json()["starter_action"]["commitment_minutes"] == 5
    assert client.post("/api/tasks/" + task_id + "/clarify", json={}).status_code == 200
    result = client.post("/api/tasks/" + task_id + "/segments", json={"title": "Vérifier l'onglet"})
    assert result.status_code == 201, result.text
    segment_id = result.json()["segments"][0]["id"]
    assert assistance(client, task_id).json()["next_action"] == {
        "action_type": "WORK_ON_SEGMENT", "target_id": segment_id,
        "label": "Vérifier l'onglet",
    }
    assert client.post("/api/tasks/" + task_id + "/segments/" + segment_id + "/complete").status_code == 200
    assert assistance(client, task_id).json()["next_action"]["action_type"] == "REVIEW_COMPLETION"
    assert assistance(client, task_id).json()["starter_action"]["commitment_minutes"] == 5
    assert client.post("/api/tasks/" + task_id + "/transition/complete").status_code == 200
    value = assistance(client, task_id).json()
    assert value["next_action"] is None
    assert value["starter_action"] is None
    assert value["strategies"] == []
    assert value["resume_point"] is None


def test_confirm_update_and_clear_resume_are_revisioned_without_history(setup):
    client, factory = setup
    task_id = task(client)
    value = assistance(client, task_id).json()
    with factory() as session:
        fact_count = len(session.scalars(select(HistoryEventRecord)).all())
    assert save(client, task_id, value, "Reprendre au tableau", confirmed=False).status_code == 422
    assert save(client, task_id, value, "  ").status_code == 422
    assert save(client, task_id, value, "x" * 241).status_code == 422
    assert assistance(client, task_id).json()["resume_revision"] == 0

    response = save(client, task_id, value, "  vérifier le mapping PLC  ")
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["resume_point"]["text"] == "vérifier le mapping PLC"
    assert saved["resume_revision"] == 1
    assert assistance(client, task_id).json()["resume_point"]["text"] == "vérifier le mapping PLC"
    assert save(client, task_id, value, "écraser une note périmée").status_code == 409
    noop = save(client, task_id, saved, "vérifier le mapping PLC")
    assert noop.status_code == 200
    assert noop.json()["resume_revision"] == 1
    updated = save(client, task_id, saved, "Ouvrir le fichier")
    assert updated.status_code == 200
    assert updated.json()["resume_revision"] == 2
    cleared = save(client, task_id, updated.json(), None)
    assert cleared.status_code == 200
    assert cleared.json()["resume_point"] is None
    assert cleared.json()["resume_revision"] == 3
    assert save(client, task_id, value, "ancienne requête").status_code == 409
    with factory() as session:
        rows = session.scalars(select(ResumePointRecord)).all()
        assert len(rows) == 1 and rows[0].text is None
        assert len(session.scalars(select(HistoryEventRecord)).all()) == fact_count


def test_stale_segment_marker_is_hidden_and_target_changes_rejected(setup):
    client, _ = setup
    task_id = task(client)
    initial = assistance(client, task_id).json()
    assert save(client, task_id, initial, "Commencer au fichier").status_code == 200
    created = client.post("/api/tasks/" + task_id + "/segments", json={"title": "Segment A"})
    assert created.status_code == 201
    fresh = assistance(client, task_id).json()
    assert fresh["next_action"]["action_type"] == "WORK_ON_SEGMENT"
    assert fresh["resume_point"] is None
    assert fresh["resume_revision"] == 1
    assert save(client, task_id, initial, "note dépassée", revision=1).status_code == 409
    replacement = save(client, task_id, fresh, "Reprendre au premier champ")
    assert replacement.status_code == 200
    assert replacement.json()["resume_point"]["target_id"] == fresh["next_action"]["target_id"]


def test_missing_or_terminal_task_does_not_save_marker(setup):
    client, _ = setup
    missing = "00000000-0000-0000-0000-000000000001"
    assert assistance(client, missing).status_code == 404
    task_id = task(client)
    before = assistance(client, task_id).json()
    assert client.post("/api/tasks/" + task_id + "/transition/complete").status_code == 200
    assert save(client, task_id, before, "ancien contexte").status_code == 422
    assert assistance(client, task_id).json()["resume_point"] is None
