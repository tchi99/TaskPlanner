"""TP-072 pure projections: thresholds, ambiguity, and voluntary responses."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.application.history import HistoryEvent, HistorySource
from app.domain.behavior import project_behavior
from app.domain.model import Task, TaskStatus
from app.domain.work_sessions import WorkSession

NOW = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)


def event(task_id, kind, at, reason=None):
    return HistoryEvent(
        id=uuid4(), occurred_at=at, recorded_at=at, entity_type="TASK",
        entity_id=task_id, task_id=task_id, event_type=kind, schema_version=1,
        source=HistorySource.USER, reason_code=reason, correlation_id=uuid4(),
        causation_id=None, payload={},
    )


def project(tasks=(), events=(), sessions=(), decomposed=(), calibration=()):
    return project_behavior(
        as_of=NOW, tasks=tasks, events=events, sessions=sessions,
        decomposed_ids=set(decomposed), calibration=calibration,
    )


def test_insufficient_samples_never_become_population_trends():
    tasks = [Task(title=str(i)) for i in range(2)]
    facts = [event(t.id, "TASK_ESTIMATE_CHANGED", NOW) for t in tasks]
    assert project(tasks, facts)["trends"] == []
    facts.append(event(tasks[0].id, "TASK_ESTIMATE_CHANGED", NOW))
    assert project(tasks, facts)["trends"] == []  # 3 events but only 2 tasks
    facts.append(event(Task(title="third").id, "TASK_ESTIMATE_CHANGED", NOW))
    result = project(tasks, facts)
    assert [t["code"] for t in result["trends"]] == ["ESTIMATES_REVISED"]
    assert result["trends"][0]["uncertainty"] == "LIMITED"
    assert result["changes_applied"] is False


def test_session_interruption_rate_does_not_count_active_sessions_or_one_task():
    sessions = []
    for index in range(3):
        first = WorkSession.start(uuid4(), None, NOW - timedelta(hours=3), None, 30)
        if index == 0:
            sessions.append(first)  # active, not a finished observation
        else:
            sessions.append(first.pause(NOW - timedelta(hours=2)).finish(NOW))
    assert project(sessions=sessions)["trends"] == []
    last = WorkSession.start(uuid4(), None, NOW - timedelta(hours=1), None, 30)
    sessions.append(last.finish(NOW))
    result = project(sessions=sessions)
    assert len(result["trends"]) == 1
    assert result["trends"][0]["code"] == "INTERRUPTION_FREQUENCY"
    assert "2 session(s) sur 3" in result["trends"][0]["description"]


def test_quiet_and_unknown_are_distinguished_and_suggestions_are_never_applied():
    old = NOW - timedelta(days=20)
    quiet = Task(title="Old event", created_at=old)
    unknown = Task(title="Legacy data", created_at=old)
    fresh = Task(title="New task", created_at=NOW)
    done = Task(title="Closed", status=TaskStatus.DONE, created_at=old)
    result = project(
        tasks=[quiet, unknown, fresh, done],
        events=[event(quiet.id, "TASK_CAPTURED", old),
                event(done.id, "TASK_CAPTURED", old)],
    )
    by_id = {(i["task_id"], i["code"]) for i in result["interventions"]}
    assert (str(quiet.id), "REVISIT_QUIET") in by_id
    assert (str(unknown.id), "REVIEW_UNKNOWN_ACTIVITY") in by_id
    assert not any(i["task_id"] in {str(fresh.id), str(done.id)}
                   for i in result["interventions"])
    assert all(i["requires_confirmation"] for i in result["interventions"])


def test_reasons_are_declared_not_inferred_and_large_tasks_are_options():
    large = Task(title="Long item", estimated_minutes=120)
    missing = event(large.id, "WORK_SESSION_PAUSED", NOW, "MISSING_INFORMATION")
    response = project(tasks=[large], events=[missing])
    assert {i["code"] for i in response["interventions"]} == {
        "CLARIFY_INFORMATION", "SPLIT_LARGE_UNIT"
    }
    assert "cause" not in response["interventions"][0]["observation"].lower()
    segmented = project(tasks=[large], events=[missing], decomposed=[large.id])
    assert {i["code"] for i in segmented["interventions"]} == {"CLARIFY_INFORMATION"}
