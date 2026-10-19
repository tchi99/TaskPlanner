from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.clarification import ClarifyTaskCommand, clarify_task
from app.application.tasks import CaptureTaskCommand, capture_task
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.history_repository import SqlHistoryRepository
from app.infrastructure.models import HistoryEventRecord, ProjectRecord, TaskRecord
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    try:
        yield engine, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_owned_type(client, name):
    scope = client.post("/api/schedule-scopes", json={"name": f"Parent-{uuid4()}"})
    assert scope.status_code == 201, scope.text
    return client.post("/api/work-types", json={"name": name, "scope_id": scope.json()["id"]})


def test_projects_work_types_and_unassigned_tasks_are_durable(db):
    engine, _ = db
    with TestClient(app) as client:
        task = client.post("/api/tasks", json={"title": "Orphan"}).json()
        assert task["project_id"] is None
        assert task["work_type_id"] is None
        project = client.post("/api/projects", json={"title": "  Build  "})
        work_type = _create_owned_type(client, "Deep work")
        assert project.status_code == 201
        assert work_type.status_code == 201
        project_id = project.json()["id"]
        type_id = work_type.json()["id"]

        assert client.get("/api/projects").json()[0]["id"] == project_id
        assert client.get(f"/api/projects/{project_id}").json()["title"] == "Build"
        assert client.get("/api/work-types").json()[0]["id"] == type_id
        assert client.get(f"/api/projects/{project_id}/tasks").json() == []
        assert client.get("/api/tasks").json()[0]["id"] == task["id"]

    with Session(engine) as session:
        record = session.get(TaskRecord, task["id"])
        assert record is not None and record.project_id is None


def test_clarification_enriches_capture_without_losing_identity_and_logs_one_command(db):
    engine, _ = db
    with TestClient(app) as client:
        capture = client.post("/api/tasks", json={
            "title": "Initial", "notes": "Private original", "estimated_minutes": 30
        }).json()
        project_id = client.post("/api/projects", json={"title": "P"}).json()["id"]
        work_type_id = _create_owned_type(client, "Focus").json()["id"]
        clarified = client.post(f"/api/tasks/{capture['id']}/clarify", json={
            "title": "  Specified  ",
            "notes": "Private enriched",
            "project_id": project_id,
            "work_type_id": work_type_id,
            "estimated_minutes": 60,
        })
        assert clarified.status_code == 200
        payload = clarified.json()
        assert payload["id"] == capture["id"]
        assert payload["created_at"] == capture["created_at"]
        assert payload["status"] == "TODO"
        assert payload["title"] == "Specified"
        assert payload["notes"] == "Private enriched"
        assert payload["project_id"] == project_id
        assert payload["work_type_id"] == work_type_id
        assert payload["estimated_minutes"] == 60
        assert client.get("/api/tasks/inbox").json() == []
        assert client.get(f"/api/projects/{project_id}/tasks").json()[0]["id"] == capture["id"]

    with Session(engine) as session:
        events = session.scalars(
            select(HistoryEventRecord).order_by(HistoryEventRecord.sequence)
        ).all()
        assert [event.event_type for event in events] == [
            "TASK_CAPTURED", "TASK_CLARIFIED",
            "TASK_ESTIMATE_CHANGED", "TASK_WORK_TYPE_CHANGED",
        ]
        assert len({event.correlation_id for event in events[1:]}) == 1
        assert len({event.id for event in events}) == 4
        assert all(event.source == "USER" for event in events)
        assert events[2].payload == {"before": 30, "after": 60}
        assert events[3].payload == {"before": None, "after": work_type_id}
        assert all("Private" not in str(event.payload) for event in events)
        assert session.get(TaskRecord, capture["id"]).created_at is not None


def test_clarify_without_metadata_preserves_unknowns_and_only_logs_clarification(db):
    engine, _ = db
    with TestClient(app) as client:
        captured = client.post("/api/tasks", json={"title": "Minimal"}).json()
        response = client.post(f"/api/tasks/{captured['id']}/clarify", json={})
        assert response.status_code == 200
        task = response.json()
        assert task["status"] == "TODO"
        assert task["project_id"] is None
        assert task["estimated_minutes"] is None
        assert task["work_type_id"] is None
        assert task["created_at"] == captured["created_at"]
        assert client.post(f"/api/tasks/{captured['id']}/clarify", json={}).status_code == 422
    with Session(engine) as session:
        events = session.scalars(select(HistoryEventRecord)).all()
        assert [event.event_type for event in events] == ["TASK_CAPTURED", "TASK_CLARIFIED"]


@pytest.mark.parametrize("relation", ["project_id", "work_type_id"])
def test_invalid_relation_rejects_clarification_atomically(db, relation):
    engine, _ = db
    with TestClient(app) as client:
        captured = client.post("/api/tasks", json={"title": "Captured"}).json()
        response = client.post(
            f"/api/tasks/{captured['id']}/clarify",
            json={relation: str(uuid4()), "estimated_minutes": 45},
        )
        assert response.status_code == 422
        assert client.get(f"/api/tasks/{captured['id']}").json()["status"] == "INBOX"
    with Session(engine) as session:
        events = session.scalars(select(HistoryEventRecord)).all()
        assert len(events) == 1
        assert events[0].event_type == "TASK_CAPTURED"


def test_inactive_project_cannot_receive_a_task(db):
    engine, _ = db
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "Inactive"}).json()["id"]
        captured = client.post("/api/tasks", json={"title": "Inbox"}).json()
        with Session(engine) as session:
            session.get(ProjectRecord, project_id).status = "COMPLETED"
            session.commit()
        response = client.post(
            f"/api/tasks/{captured['id']}/clarify", json={"project_id": project_id}
        )
        assert response.status_code == 422
        assert client.get(f"/api/tasks/{captured['id']}").json()["status"] == "INBOX"


def test_explicit_attachment_and_detachment_does_not_implicitly_clarify(db):
    engine, _ = db
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"title": "P"}).json()["id"]
        captured = client.post("/api/tasks", json={"title": "Inbox"}).json()
        attached = client.patch(f"/api/tasks/{captured['id']}/project", json={
            "project_id": project_id
        })
        assert attached.status_code == 200
        assert attached.json()["status"] == "INBOX"
        assert attached.json()["created_at"] == captured["created_at"]
        assert client.patch(f"/api/tasks/{captured['id']}/project", json={
            "project_id": project_id
        }).status_code == 200
        detached = client.patch(f"/api/tasks/{captured['id']}/project", json={
            "project_id": None
        })
        assert detached.status_code == 200
        assert detached.json()["project_id"] is None
        assert client.get(f"/api/projects/{project_id}/tasks").json() == []
    with Session(engine) as session:
        events = session.scalars(select(HistoryEventRecord)).all()
        assert [event.event_type for event in events] == ["TASK_CAPTURED"]


def test_validation_and_missing_resources(db):
    _, _factory = db
    with TestClient(app) as client:
        assert client.post("/api/projects", json={"title": "  "}).status_code == 422
        assert client.post("/api/work-types", json={"name": "  "}).status_code == 422
        assert client.get(f"/api/projects/{uuid4()}").status_code == 404
        assert client.get(f"/api/projects/{uuid4()}/tasks").status_code == 404
        assert client.get(f"/api/tasks/{uuid4()}").status_code == 404
        assert client.post(f"/api/tasks/{uuid4()}/clarify", json={}).status_code == 404
        task = client.post("/api/tasks", json={"title": "Validation"}).json()
        assert client.post(f"/api/tasks/{task['id']}/clarify", json={
            "estimated_minutes": 0
        }).status_code == 422
        assert client.post(f"/api/tasks/{task['id']}/clarify", json={
            "due_at": "2026-10-10T10:00:00"
        }).status_code == 422
        assert client.patch(f"/api/tasks/{task['id']}/project", json={
            "project_id": str(uuid4())
        }).status_code == 422


class BrokenHistoryRepository(SqlHistoryRepository):
    def append_many(self, events):
        super().append_many(events)
        # Invalid enum/check constraint proves no half-clarified state commits.
        for pending in self._session.new:
            if isinstance(pending, HistoryEventRecord):
                pending.source = "INVALID_SOURCE"


class BrokenHistoryUow(SqlAlchemyUnitOfWork):
    def __enter__(self):
        super().__enter__()
        assert self.session is not None
        self.history = BrokenHistoryRepository(self.session)
        return self


def test_history_failure_rolls_back_clarification_and_estimate(db):
    engine, factory = db
    task = capture_task(
        SqlAlchemyUnitOfWork(factory), CaptureTaskCommand(title="Rollback")
    )
    with pytest.raises(IntegrityError):
        clarify_task(
            BrokenHistoryUow(factory),
            ClarifyTaskCommand(
                task_id=task.id,
                changed_fields=frozenset({"estimated_minutes"}),
                estimated_minutes=40,
            ),
        )
    with Session(engine) as session:
        record = session.get(TaskRecord, str(task.id))
        assert record.status == "INBOX"
        assert record.estimated_minutes is None
        events = session.scalars(select(HistoryEventRecord)).all()
        assert [event.event_type for event in events] == ["TASK_CAPTURED"]
