"""TP-051: AI explains deterministic facts but cannot choose or mutate."""
import json
from datetime import date
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.arbitration import (
    ArbitrationDraft, ArbitrationNotConfigured, ArbitrationUnavailable,
    OptionExplanation,
)
from app.config import Settings
from app.domain.planning import propose_plan
from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import HistoryEventRecord, TaskRecord
from app.infrastructure.openai_arbitration import OpenAIArbitrationAssistant
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.main import app
from app.server.arbitration import get_arbitration_assistant

WEEK = "/api/capacity/weeks/2026-10-05"


class FakeAssistant:
    def __init__(self):
        self.proposals = []

    def explain(self, proposal):
        self.proposals.append(proposal)
        return ArbitrationDraft(explanations=[
            OptionExplanation(option_index=i, explanation=f"Compromis de l'option {i}",
                              question=None)
            for i in range(len(proposal.options))
        ])


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    assistant = FakeAssistant()
    app.dependency_overrides[get_uow] = lambda: SqlAlchemyUnitOfWork(factory)
    app.dependency_overrides[get_arbitration_assistant] = lambda: assistant
    try:
        with TestClient(app) as client:
            yield client, engine, assistant
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def make_task(client, title, protection, estimate):
    task_id = client.post("/api/tasks", json={
        "title": title, "estimated_minutes": estimate,
    }).json()["id"]
    assert client.post(f"/api/tasks/{task_id}/clarify", json={}).status_code == 200
    assert client.patch(f"/api/tasks/{task_id}/protection", json={
        "protection": protection, "confirm_downgrade": protection == "FLEXIBLE",
    }).status_code == 200
    return task_id


def test_arbitration_preserves_options_protected_constraints_and_database(runtime):
    client, engine, assistant = runtime
    assert client.post(WEEK + "/blocks", json={
        "starts_at": "2026-10-05T08:00:00-04:00",
        "ends_at": "2026-10-05T09:00:00-04:00",
    }).status_code == 201
    protected = make_task(client, "Must", "PROTECTED", 45)
    flexible = make_task(client, "May", "FLEXIBLE", 30)
    with Session(engine) as session:
        before = len(session.scalars(select(HistoryEventRecord)).all())
    data = client.post(WEEK + "/arbitration-suggestions", json={
        "task_ids": [protected, flexible],
    })
    assert data.status_code == 200, data.text
    result = data.json()
    assert result["state"] == "PROPOSED"
    assert result["source"] == "AI_SUGGESTION"
    proposal = result["proposal"]
    assert proposal["baseline"]["status"] == "OVER_CAPACITY"
    assert proposal["baseline"]["known_demand_minutes"] == 75
    assert [o["kind"] for o in proposal["options"]] == [
        "KEEP", "DEFER", "REVIEW_SCOPE", "CONSIDER_DELEGATION",
    ]
    defer = proposal["options"][1]
    assert defer["excluded_task_ids"] == [flexible]
    assert defer["requires_confirmation"]
    assert all(protected not in option["excluded_task_ids"] for option in proposal["options"])
    assert proposal["options"][2]["capacity"] is None
    assert [a["option_index"] for a in result["explanations"]] == list(
        range(len(proposal["options"]))
    )
    assert assistant.proposals[0].baseline.status.value == "OVER_CAPACITY"
    assert client.get("/api/tasks/" + protected).json()["protection"] == "PROTECTED"
    assert len(client.get(WEEK).json()["blocks"]) == 1
    with Session(engine) as session:
        assert len(session.scalars(select(TaskRecord)).all()) == 2
        assert len(session.scalars(select(HistoryEventRecord)).all()) == before


def test_errors_and_invalid_inputs_are_safe(runtime):
    client, _, assistant = runtime
    not_found = str(uuid4())
    path = WEEK + "/arbitration-suggestions"
    assert client.post(path, json={"task_ids": [not_found]}).status_code == 404
    assert client.post(path, json={"task_ids": [not_found, not_found]}).status_code == 422
    assert client.post("/api/capacity/weeks/2026-10-06/arbitration-suggestions",
                       json={"task_ids": []}).status_code == 422
    assert assistant.proposals == []

    class Missing:
        def explain(self, proposal):
            raise ArbitrationNotConfigured("private key")
    app.dependency_overrides[get_arbitration_assistant] = lambda: Missing()
    response = client.post(path, json={"task_ids": []})
    assert response.status_code == 503
    assert "private" not in response.text

    class Broken:
        def explain(self, proposal):
            raise ArbitrationUnavailable("private provider response")
    app.dependency_overrides[get_arbitration_assistant] = lambda: Broken()
    response = client.post(path, json={"task_ids": []})
    assert response.status_code == 502
    assert "private" not in response.text

    class WrongOption:
        def explain(self, proposal):
            return {"explanations": [{"option_index": 100, "explanation": "Unsupported"}]}
    app.dependency_overrides[get_arbitration_assistant] = lambda: WrongOption()
    assert client.post(path, json={"task_ids": []}).status_code == 502

    class InvalidText:
        def explain(self, proposal):
            return {"explanations": [{"option_index": 0, "explanation": "   "}]}
    app.dependency_overrides[get_arbitration_assistant] = lambda: InvalidText()
    assert client.post(path, json={"task_ids": []}).status_code == 502


@pytest.mark.parametrize("payload", [
    {"explanations": []},
    {"explanations": [{"option_index": 0, "explanation": " "}]},
    {"explanations": [{"option_index": -1, "explanation": "A"}]},
    {"explanations": [{"option_index": 0, "explanation": "A", "priority": "urgent"}]},
    {"explanations": [
        {"option_index": 0, "explanation": "A"},
        {"option_index": 0, "explanation": "B"},
    ]},
])
def test_provider_schema_rejects_untrusted_shapes(payload):
    with pytest.raises(ValidationError):
        ArbitrationDraft.model_validate(payload)


def test_provider_optional_sends_only_deterministic_summary():
    proposal = propose_plan(date(2026, 10, 5), [], [])
    with pytest.raises(ArbitrationNotConfigured):
        OpenAIArbitrationAssistant(Settings(openai_api_key=None)).explain(proposal)

    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({
                "explanations": [{"option_index": 0, "explanation": "Conserver le plan",
                                  "question": None}]
            })}}]
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        draft = OpenAIArbitrationAssistant(
            Settings(openai_api_key=SecretStr("fake-key")), client
        ).explain(proposal)
    assert draft.explanations[0].option_index == 0
    assert requests[0].url.host == "api.openai.com"
    sent = json.loads(requests[0].content)
    facts = json.loads(sent["messages"][1]["content"])
    assert facts["baseline"]["status"] == "FEASIBLE"
    assert facts["options"][0]["kind"] == "KEEP"
    assert "event_id" not in str(sent) and "fake-key" not in str(sent)
    assert "task_ids" not in str(sent)

    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": '{"explanations":[{"option_index":0,"explanation":" "}]}'}}
        ]})
    )) as client:
        with pytest.raises(ArbitrationUnavailable):
            OpenAIArbitrationAssistant(
                Settings(openai_api_key=SecretStr("fake-key")), client
            ).explain(proposal)
