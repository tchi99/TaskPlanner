"""TP-050: suggestions are separate from the task aggregate and user choice."""
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.decomposition import (
    DecompositionContext, DecompositionDraft, SuggestedWorkItem,
)
from app.config import Settings
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, TaskSegmentRecord
from app.infrastructure.openai_decomposition import (
    DecompositionNotConfigured, DecompositionUnavailable, OpenAIDecompositionAssistant,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.decomposition import get_decomposition_assistant


class FakeAssistant:
    def __init__(self):
        self.contexts = []

    def suggest(self, context):
        self.contexts.append(context)
        return DecompositionDraft(
            segments=[
                SuggestedWorkItem(title="Prepare outline", duration_min_minutes=15,
                                  duration_max_minutes=30),
                SuggestedWorkItem(title="Review outline", depends_on=[1]),
            ],
            subtasks=[SuggestedWorkItem(title="Review with stakeholder")],
            clarification_questions=["What is the deadline?"],
        )


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    assistant = FakeAssistant()
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_decomposition_assistant] = lambda: assistant
    try:
        with TestClient(app) as client:
            yield client, engine, assistant
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def make_task(client, clarify=True):
    result = client.post("/api/tasks", json={
        "title": "Draft plan", "notes": "Scope needs review",
        "estimated_minutes": 90,
    })
    assert result.status_code == 201
    task_id = result.json()["id"]
    if clarify:
        assert client.post("/api/tasks/" + task_id + "/clarify", json={}).status_code == 200
    return task_id


def test_proposal_does_not_create_tasks_segments_or_history(runtime):
    client, engine, assistant = runtime
    task_id = make_task(client)
    path = "/api/tasks/" + task_id
    existing = client.post(path + "/segments", json={
        "title": "Already existing",
    })
    assert existing.status_code == 201
    with Session(engine) as session:
        events_before = len(session.scalars(select(HistoryEventRecord)).all())
        segments_before = len(session.scalars(select(TaskSegmentRecord)).all())
    response = client.post(path + "/decomposition-suggestions")
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["source"] == "AI_SUGGESTION"
    assert proposal["state"] == "PROPOSED"
    assert proposal["task_id"] == task_id
    assert proposal["segments"][1]["depends_on"] == [1]
    assert proposal["segments"][0]["duration_max_minutes"] == 30
    assert proposal["subtasks"][0]["title"] == "Review with stakeholder"
    assert proposal["clarification_questions"] == ["What is the deadline?"]
    assert assistant.contexts[0].existing_segments == ("Already existing",)
    assert assistant.contexts[0].notes == "Scope needs review"
    with Session(engine) as session:
        assert len(session.scalars(select(HistoryEventRecord)).all()) == events_before
        assert len(session.scalars(select(TaskSegmentRecord)).all()) == segments_before
    assert len(client.get(path + "/detail").json()["segments"]) == 1
    # Explicit existing command is still required to apply one suggestion.
    assert client.post(path + "/segments", json={
        "title": proposal["segments"][0]["title"]
    }).status_code == 201


def test_only_open_clarified_tasks_can_be_suggested(runtime):
    client, _, assistant = runtime
    inbox = make_task(client, clarify=False)
    assert client.post("/api/tasks/" + inbox + "/decomposition-suggestions").status_code == 422
    task_id = make_task(client)
    assert client.post("/api/tasks/" + task_id + "/transition/complete").status_code == 200
    assert client.post("/api/tasks/" + task_id + "/decomposition-suggestions").status_code == 422
    assert client.post("/api/tasks/" + str(uuid4()) + "/decomposition-suggestions").status_code == 404
    assert assistant.contexts == []


def test_missing_provider_or_upstream_failure_is_safe(runtime):
    client, engine, assistant = runtime
    task_id = make_task(client)
    class Missing:
        def suggest(self, context):
            raise DecompositionNotConfigured("private credential")
    app.dependency_overrides[get_decomposition_assistant] = lambda: Missing()
    path = "/api/tasks/" + task_id + "/decomposition-suggestions"
    response = client.post(path)
    assert response.status_code == 503
    assert "private" not in response.text
    class Broken:
        def suggest(self, context):
            raise DecompositionUnavailable("private provider body")
    app.dependency_overrides[get_decomposition_assistant] = lambda: Broken()
    response = client.post(path)
    assert response.status_code == 502
    assert "private" not in response.text
    assert client.get("/api/tasks/" + task_id + "/detail").json()["segments"] == []


@pytest.mark.parametrize("payload", [
    {"segments": [{"title": "  "}]},
    {"segments": [{"title": "A", "duration_min_minutes": 30,
                   "duration_max_minutes": 10}]},
    {"segments": [{"title": "A", "duration_min_minutes": 0,
                   "duration_max_minutes": 10}]},
    {"segments": [{"title": "A", "depends_on": [1]}]},
    {"segments": [{"title": "A"}, {"title": "A"}]},
    {"segments": [{"title": "A"}, {"title": "B", "depends_on": [1, 1]}]},
    {"segments": [], "subtasks": [], "clarification_questions": []},
])
def test_untrustworthy_ai_output_is_rejected(payload):
    with pytest.raises(ValidationError):
        DecompositionDraft.model_validate(payload)


def test_openai_adapter_is_optional_and_strict():
    context = DecompositionContext(
        task_id=uuid4(), title="Do work", notes="Notes", estimated_minutes=60,
        existing_segments=("Current",),
    )
    with pytest.raises(DecompositionNotConfigured):
        OpenAIDecompositionAssistant(Settings(openai_api_key=None)).suggest(context)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "segments": [{"title": "Next", "duration_min_minutes": 15,
                              "duration_max_minutes": 30, "depends_on": []}],
                "subtasks": [], "clarification_questions": [],
            })}}]
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assistant = OpenAIDecompositionAssistant(
            Settings(openai_api_key=SecretStr("fake-key")), client
        )
        draft = assistant.suggest(context)
    assert draft.segments[0].title == "Next"
    assert requests[0].url.host == "api.openai.com"
    body = json.loads(requests[0].content)
    assert body["messages"][1]["content"].find("Current") >= 0
    assert "fake-key" not in str(body)
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": '{"segments":[{"title":"No","depends_on":[1]}]}'}}]
        })
    )) as client:
        with pytest.raises(DecompositionUnavailable):
            OpenAIDecompositionAssistant(
                Settings(openai_api_key=SecretStr("fake-key")), client
            ).suggest(context)
