"""TP-023A HTTP contract: future-only, atomic, immutable and idempotent edits."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.infrastructure import models  # noqa: F401
from app.infrastructure.db import Base
from app.infrastructure.models import (
    AvailabilityExceptionRecord, ConfirmedTimeBlockRecord,
    HistoryEventRecord, RecurringAvailabilityRevisionRecord,
    WeeklyScheduleCommandRecord,
)
from app.infrastructure.uow import SqlAlchemyUnitOfWork, get_uow
from app.infrastructure.history_repository import SqlHistoryRepository
from app.domain.time_blocks import ConfirmedTimeBlock
from app.main import app

ZONE = "America/Toronto"
ROOT = "/api/availability/weekly-schedule"


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'weekly.sqlite'}",
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
    return today + timedelta(days=14 + (7-today.weekday()) % 7)


def rule(client, start, *, weekdays=(0, 1, 2), begins="09:00", ends="10:00"):
    response = client.post("/api/availability/rules", json={
        "effective_from": str(start), "timezone_name": ZONE,
        "days_of_week": list(weekdays),
        "starts_at_local": begins, "ends_at_local": ends,
        "kind": "GENERAL",
    })
    assert response.status_code == 201, response.text
    return response.json()


def draft(client, effect, slots, *, weekday=1, kind="GENERAL", work_type_id=None,
          decisions=None):
    grid = client.get(ROOT, params={
        "effective_from": str(effect), "timezone_name": ZONE,
    })
    assert grid.status_code == 200, grid.text
    return {
        "effective_from": str(effect), "timezone_name": ZONE,
        "sections": [{"weekday": weekday, "kind": kind,
                      "work_type_id": work_type_id, "slots": slots}],
        "expected_versions": grid.json()["source_versions"],
        "exception_decisions": decisions or [],
    }


def slot(start, end):
    return {"starts_at_local": start, "ends_at_local": end}


def preview(client, body):
    response = client.post(ROOT + "/preview", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, body, token, *, command_id=None, **kwargs):
    return client.post(ROOT + "/confirm", json={
        **body, "fingerprint": token["fingerprint"], "confirmed": True,
        "command_id": str(command_id or uuid4()), **kwargs,
    })


def occurrences(client, day):
    response = client.get("/api/availability/rules/occurrences", params={
        "from": str(day), "to": str(day + timedelta(days=7)),
    })
    assert response.status_code == 200, response.text
    return {v["original_local_date"]: v["starts_at"]
            for v in response.json()["occurrences"]}


def test_weekday_split_future_versions_same_day_repeat_and_idempotence(runtime):
    client, factory = runtime
    start = monday()
    original = rule(client, start)
    future = client.patch(f"/api/availability/rules/{original['id']}", json={
        "effective_from": str(start+timedelta(days=28)),
        "timezone_name": ZONE, "days_of_week": [0, 1, 2],
        "starts_at_local": "10:00", "ends_at_local": "11:00",
        "kind": "GENERAL", "expected_version": 1,
    })
    assert future.status_code == 200, future.text
    effect = start + timedelta(days=7)
    body = draft(client, effect, [slot("12:00", "13:00")])
    token = preview(client, body)
    assert len(token["series_cutovers"]) == 1
    assert token["series_cutovers"][0]["future_revisions_superseded"] == [2]
    assert len(token["derived_rule_ids"]) == 2
    assert token["cell_changes"][0]["before"][0]["starts_at_local"] == "09:00"
    assert token["cell_changes"][0]["after"][0]["starts_at_local"] == "12:00"
    assert token["calendar_verified"] is False
    command = uuid4()
    applied = confirm(client, body, token, command_id=command)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"]
    same = confirm(client, body, token, command_id=command)
    assert same.status_code == 200 and same.json() == applied.json()
    reused = confirm(client, {**body, "effective_from": str(effect+timedelta(days=1))},
                     token, command_id=command)
    assert reused.status_code == 409

    previous = occurrences(client, start)
    assert len(previous) == 3
    next_week = occurrences(client, effect)
    assert len(next_week) == 3
    assert datetime.fromisoformat(next_week[str(effect+timedelta(days=1))]).astimezone(
        ZoneInfo(ZONE)).hour == 12
    far = occurrences(client, start+timedelta(days=28))
    assert [datetime.fromisoformat(far[str(start+timedelta(days=28+i))]).astimezone(
        ZoneInfo(ZONE)).hour for i in range(3)] == [10, 12, 10]

    second = draft(client, effect, [slot("14:00", "15:00")])
    changed = preview(client, second)
    updated = confirm(client, second, changed)
    assert updated.status_code == 200, updated.text
    with factory() as session:
        rows = session.scalars(select(RecurringAvailabilityRevisionRecord)).all()
        assert any(r.supersedes_future and r.effective_from == effect
                   for r in rows)
        assert session.scalar(select(func.count()).select_from(WeeklyScheduleCommandRecord)) == 2
        # An immutable source may have a terminal revision with the same date
        # as the original, now permitted by the migration.
        assert any(r.supersedes_future and r.number == 2 for r in rows)
    latest = occurrences(client, effect)
    assert datetime.fromisoformat(latest[str(effect+timedelta(days=1))]).astimezone(
        ZoneInfo(ZONE)).hour == 14


def test_noop_is_no_audit_and_stale_preview_returns_409(runtime):
    client, factory = runtime
    start = monday()
    first = rule(client, start, weekdays=(1,))
    body = draft(client, start, [slot("09:00", "10:00")])
    token = preview(client, body)
    assert not token["has_changes"]
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(HistoryEventRecord))
    result = confirm(client, body, token)
    assert result.status_code == 200 and not result.json()["applied"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HistoryEventRecord)) == before
    new = draft(client, start, [slot("12:00", "13:00")])
    old_token = preview(client, new)
    rule(client, start, weekdays=(4,))
    assert confirm(client, new, old_token).status_code == 409


def test_exception_remap_and_rollback_of_all_changes_and_audit(runtime, monkeypatch):
    client, factory = runtime
    start = monday()
    original = rule(client, start)
    wednesday = start + timedelta(days=2)
    exception = {"action": "CANCEL", "rule_id": original["id"],
                 "original_local_date": str(wednesday), "timezone_name": ZONE}
    token = client.post("/api/availability/exceptions/preview", json=exception)
    assert token.status_code == 200, token.text
    made = client.post("/api/availability/exceptions", json={
        **exception, "expected_fingerprint": token.json()["fingerprint"]})
    assert made.status_code == 201, made.text
    edit = draft(client, start, [slot("12:00", "13:00")])
    plan = preview(client, edit)
    assert len(plan["exception_remaps"]) == 1
    assert not plan["unresolved_exceptions"]
    real_append = SqlHistoryRepository.append
    def failed_append(self, event):
        if event.event_type == "AVAILABILITY_RULE_CREATED":
            raise RuntimeError("inject rollback after writes")
        return real_append(self, event)
    monkeypatch.setattr(SqlHistoryRepository, "append", failed_append)
    with pytest.raises(RuntimeError, match="inject rollback"):
        confirm(client, edit, plan)
    monkeypatch.setattr(SqlHistoryRepository, "append", real_append)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RecurringAvailabilityRevisionRecord)) == 1
        saved = session.get(AvailabilityExceptionRecord, made.json()["id"])
        assert saved.rule_id == original["id"] and saved.version == 1
        assert session.scalar(select(func.count()).select_from(WeeklyScheduleCommandRecord)) == 0
    applied = confirm(client, edit, plan)
    assert applied.status_code == 200, applied.text
    with factory() as session:
        saved = session.get(AvailabilityExceptionRecord, made.json()["id"])
        assert saved.rule_id != original["id"] and saved.version == 2
        batch = session.scalars(select(HistoryEventRecord).where(
            HistoryEventRecord.correlation_id == applied.json()["correlation_id"]
        )).all()
        assert len(batch) >= 4
        assert all(r.task_id is None for r in batch)


def test_future_booking_outside_93_day_preview_is_not_deleted(runtime):
    client, factory = runtime
    start = monday()
    rule(client, start, weekdays=(1,))
    far = start + timedelta(days=120)
    while far.weekday() != 1:
        far += timedelta(days=1)
    task = client.post("/api/tasks", json={"title": "Future reserved"}).json()["id"]
    at = datetime.combine(far, datetime.min.time(), ZoneInfo(ZONE)).replace(hour=9)
    booking = ConfirmedTimeBlock(
        week_start=far-timedelta(days=far.weekday()), task_id=UUID(task),
        segment_id=None, work_type_id=None, starts_at=at, ends_at=at+timedelta(hours=1),
    )
    with SqlAlchemyUnitOfWork(factory) as uow:
        uow.lock_planning()
        uow.time_blocks.add(booking)
        uow.commit()
    body = draft(client, start, [])
    token = preview(client, body)
    assert any(c["booking_id"] == str(booking.id) and c["new"]
               for c in token["booking_conflicts"])
    assert confirm(client, body, token).status_code == 422
    applied = confirm(client, body, token, acknowledge_conflicts=True)
    assert applied.status_code == 200, applied.text
    with factory() as session:
        stored = session.get(ConfirmedTimeBlockRecord, str(booking.id))
        assert stored.status == "CONFIRMED" and stored.revision == 1


def test_real_competing_sqlite_confirmations_only_one_commits(runtime):
    client, factory = runtime
    start = monday()
    rule(client, start, weekdays=(1,))
    body = draft(client, start, [slot("12:00", "13:00")])
    token = preview(client, body)
    def send(_):
        return confirm(client, body, token).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(send, range(2)))
    assert sorted(codes) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WeeklyScheduleCommandRecord)) == 1


def test_dst_nonexistent_civil_time_is_reported_and_never_silently_applied(runtime):
    client, factory = runtime
    start = monday()
    # The second Sunday of March is the Toronto DST spring gap.
    gap = __import__("datetime").date(datetime.now(ZoneInfo(ZONE)).year + 1, 3, 8)
    while gap.weekday() != 6:
        gap += timedelta(days=1)
    body = draft(client, gap, [slot("02:30", "03:30")], weekday=6)
    token = preview(client, body)
    assert any(issue["reason"] == "NONEXISTENT_LOCAL_TIME"
               for issue in token["civil_time_issues"])
    response = confirm(client, body, token)
    assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            WeeklyScheduleCommandRecord)) == 0


def test_read_grid_includes_stable_rule_sources(runtime):
    client, _ = runtime
    start = monday()
    created = rule(client, start, weekdays=(1,))
    fetched = client.get(ROOT, params={
        "effective_from": str(start), "timezone_name": ZONE,
    })
    assert fetched.status_code == 200
    cell = next(v for v in fetched.json()["sections"] if v["weekday"] == 1)
    assert cell["slots"][0]["sources"] == [{
        "rule_id": created["id"], "revision": 1,
    }]


def test_removing_categorized_interval_restores_general_null(runtime):
    client, _ = runtime
    start = monday()
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    rule(client, start, weekdays=(1,), begins="09:00", ends="12:00")
    category = client.post("/api/availability/rules", json={
        "effective_from": str(start), "timezone_name": ZONE,
        "days_of_week": [1], "starts_at_local": "09:00",
        "ends_at_local": "10:00", "kind": "CATEGORIZED",
        "work_type_id": focus, "mode": "PROTECTED",
    })
    assert category.status_code == 201, category.text
    edit = draft(client, start, [], kind="CATEGORIZED",
                 weekday=1, work_type_id=focus)
    token = preview(client, edit)
    assert token["has_changes"]
    assert confirm(client, edit, token).status_code == 200
    effective = client.get("/api/availability/effective", params={
        "from": str(start), "to": str(start + timedelta(days=7)),
        "timezone_name": ZONE,
    })
    assert effective.status_code == 200
    blocks = effective.json()["blocks"]
    assert blocks and all(v["work_type_id"] is None for v in blocks)
    assert sum(v["minutes"] for v in blocks) == 180
