from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.segments import transition_segment
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.history_repository import SqlHistoryRepository
from app.infrastructure.models import HistoryEventRecord, TaskRecord, TaskSegmentRecord
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


def clarified(client):
    task = client.post(
        "/api/tasks", json={"title": "Private parent", "estimated_minutes": 120}
    ).json()
    assert client.post(f"/api/tasks/{task['id']}/clarify", json={}).status_code == 200
    return task["id"]


def test_projection_lifecycle_history_and_atomic_propagation(db):
    engine, _ = db
    with TestClient(app) as client:
        task_id = clarified(client)
        path = f"/api/tasks/{task_id}"
        work_type_id = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
        response = client.post(path + "/segments", json={
            "title": "Private A", "estimated_minutes": 20,
            "work_type_id": work_type_id,
        })
        assert response.status_code == 201
        a = response.json()["segments"][0]
        assert a["effective_work_type_id"] == work_type_id
        assert a["work_type_origin"] == "SEGMENT_OVERRIDE"
        assert a["effective_protection"] == "REPLANNABLE"
        response = client.post(path + "/segments", json={"title": "B"})
        assert response.status_code == 201
        b = response.json()["segments"][1]
        projection = response.json()
        assert projection["effective_estimate"] == {
            "source": "SEGMENTS", "known_subtotal_minutes": 20,
            "unestimated_units": 1, "total_minutes": None, "incomplete": True,
        }
        assert projection["next_action"]["target_id"] == a["id"]
        assert projection["status"] == "TODO"

        edit = client.patch(path + f"/segments/{a['id']}", json={
            "title": "Private renamed A", "estimated_minutes": 30,
        })
        assert edit.status_code == 200
        assert edit.json()["segments"][0]["id"] == a["id"]
        reorder = client.put(path + "/segments/order", json={
            "segment_ids": [b["id"], a["id"]]
        })
        assert reorder.status_code == 200
        assert [x["id"] for x in reorder.json()["segments"]] == [b["id"], a["id"]]
        assert reorder.json()["next_action"]["target_id"] == b["id"]
        start = client.post(path + f"/segments/{b['id']}/start")
        assert start.status_code == 200
        assert start.json()["status"] == "IN_PROGRESS"
        assert client.delete(path + f"/segments/{b['id']}").status_code == 422
        assert client.post(path + f"/segments/{b['id']}/complete").status_code == 200
        cancelled = client.post(path + f"/segments/{a['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["ready_for_completion"] is True
        assert cancelled.json()["next_action"]["action_type"] == "REVIEW_COMPLETION"
        assert cancelled.json()["progress"]["completed_segments"] == 1
        assert cancelled.json()["progress"]["cancelled_segments"] == 1
        assert cancelled.json()["progress"]["completion_percent"] == 50
        assert client.post(path + "/transition/complete").json()["status"] == "DONE"
        assert client.post(path + "/segments", json={"title": "Late"}).status_code == 422
        assert client.post(path + "/transition/reopen").json()["status"] == "IN_PROGRESS"

    with Session(engine) as session:
        events = session.scalars(
            select(HistoryEventRecord)
            .where(HistoryEventRecord.task_id == task_id)
            .order_by(HistoryEventRecord.sequence)
        ).all()
        kinds = [e.event_type for e in events]
        assert "SEGMENT_RENAMED" in kinds
        assert "SEGMENT_ESTIMATE_CHANGED" in kinds
        assert kinds.count("SEGMENT_REORDERED") == 2
        started = next(e for e in events if e.event_type == "SEGMENT_STARTED")
        propagated = next(e for e in events if e.event_type == "TASK_STARTED")
        assert started.source == "USER"
        assert propagated.source == "SYSTEM_RULE"
        assert started.correlation_id == propagated.correlation_id
        assert propagated.causation_id == started.id
        assert len({
            e.correlation_id for e in events
            if e.event_type in {"SEGMENT_RENAMED", "SEGMENT_ESTIMATE_CHANGED"}
        }) == 1
        assert all("Private" not in str(e.payload) for e in events)


def test_reorder_and_safe_removal_preserve_identity_and_history(db):
    engine, _ = db
    with TestClient(app) as client:
        task_id = clarified(client)
        path = f"/api/tasks/{task_id}"
        for title in ("A", "B", "C"):
            assert client.post(path + "/segments", json={"title": title}).status_code == 201
        old = client.get(path + "/detail").json()["segments"]
        ids = [s["id"] for s in old]
        assert client.put(path + "/segments/order", json={
            "segment_ids": list(reversed(ids))
        }).status_code == 200
        saved = client.get(path + "/detail").json()["segments"]
        assert [s["id"] for s in saved] == list(reversed(ids))
        assert [s["position"] for s in saved] == [0, 1, 2]
        assert client.patch(path + f"/segments/{ids[0]}", json={
            "title": "A", "estimated_minutes": None, "work_type_id": None
        }).status_code == 200
        result = client.delete(path + f"/segments/{ids[0]}")
        assert result.status_code == 200
        assert len(result.json()["segments"]) == 2
        assert client.delete(path + f"/segments/{ids[0]}").status_code == 422
        assert client.put(path + "/segments/order", json={
            "segment_ids": [ids[1], ids[1]]
        }).status_code == 422

    with Session(engine) as session:
        assert session.get(TaskSegmentRecord, ids[0]) is None
        events = session.scalars(
            select(HistoryEventRecord)
            .where(HistoryEventRecord.entity_id == ids[0])
            .order_by(HistoryEventRecord.sequence)
        ).all()
        assert events[0].event_type == "SEGMENT_ADDED"
        assert events[-1].event_type == "SEGMENT_REMOVED"
        assert not any(e.event_type == "SEGMENT_RENAMED" for e in events)


def test_invalid_updates_and_unclarified_tasks_fail_without_side_effect(db):
    _, _factory = db
    with TestClient(app) as client:
        inbox = client.post("/api/tasks", json={"title": "Inbox"}).json()["id"]
        assert client.post(f"/api/tasks/{inbox}/segments", json={"title": "Forbidden"}).status_code == 422
        task_id = clarified(client)
        other_id = clarified(client)
        path = f"/api/tasks/{task_id}"
        segment = client.post(path + "/segments", json={"title": "A"}).json()["segments"][0]
        ident = segment["id"]
        assert client.patch(path + f"/segments/{ident}", json={"title": None}).status_code == 422
        assert client.patch(path + f"/segments/{ident}", json={"estimated_minutes": 0}).status_code == 422
        assert client.patch(path + f"/segments/{ident}", json={
            "work_type_id": str(uuid4())
        }).status_code == 422
        assert client.post(f"/api/tasks/{other_id}/segments/{ident}/start").status_code == 422
        assert client.post(path + "/transition/start").status_code == 422
        assert client.get(f"/api/tasks/{uuid4()}/detail").status_code == 404
        assert client.get(path + "/detail").json()["status"] == "TODO"


class BrokenHistoryRepository(SqlHistoryRepository):
    def append_many(self, events):
        super().append_many(events)
        for row in self._session.new:
            if isinstance(row, HistoryEventRecord):
                row.source = "INVALID_SOURCE"


class BrokenHistoryUow(SqlAlchemyUnitOfWork):
    def __enter__(self):
        super().__enter__()
        assert self.session is not None
        self.history = BrokenHistoryRepository(self.session)
        return self


def test_rollback_parent_segment_and_history_together(db):
    engine, factory = db
    with TestClient(app) as client:
        task_id = clarified(client)
        segment_id = client.post(f"/api/tasks/{task_id}/segments", json={
            "title": "Start"
        }).json()["segments"][0]["id"]
    with pytest.raises(IntegrityError):
        transition_segment(BrokenHistoryUow(factory), UUID(task_id), UUID(segment_id), "start")
    with Session(engine) as session:
        assert session.get(TaskRecord, task_id).status == "TODO"
        assert session.get(TaskSegmentRecord, segment_id).status == "TODO"
        assert session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.entity_id == segment_id,
            HistoryEventRecord.event_type == "SEGMENT_STARTED",
        )).all() == []
