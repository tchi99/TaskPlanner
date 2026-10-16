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


def test_shared_weekday_series_two_windows_and_day_off_preserve_untouched_days(runtime):
    """TP-023C: editing Tuesday/Wednesday never rewrites other weekdays or history."""
    client, factory = runtime
    start = monday()
    rule(client, start, weekdays=(0, 1, 2, 3, 4))
    effect = start + timedelta(days=7)
    body = draft(client, effect, [slot("11:00", "12:00"),
                                  slot("13:00", "14:00")], weekday=1)
    body["sections"].append({
        "weekday": 2, "kind": "GENERAL", "work_type_id": None, "slots": [],
    })
    token = preview(client, body)
    assert token["has_changes"]
    assert len(token["cell_changes"]) == 2
    assert token["invalid_conflicts"] == []
    saved = confirm(client, body, token)
    assert saved.status_code == 200, saved.text
    assert saved.json()["applied"]
    assert saved.json()["calendar_written"] is False

    def daily_windows(week):
        response = client.get("/api/availability/rules/occurrences", params={
            "from": str(week), "to": str(week + timedelta(days=7)),
        })
        assert response.status_code == 200, response.text
        result = {}
        for occurrence in response.json()["occurrences"]:
            day = occurrence["original_local_date"]
            beginning = datetime.fromisoformat(occurrence["starts_at"]).astimezone(ZoneInfo(ZONE))
            ending = datetime.fromisoformat(occurrence["ends_at"]).astimezone(ZoneInfo(ZONE))
            result.setdefault(day, []).append((beginning.strftime("%H:%M"),
                                                ending.strftime("%H:%M")))
        return {day: sorted(intervals) for day, intervals in result.items()}

    previous = daily_windows(start)
    assert all(previous[str(start + timedelta(days=i))] == [("09:00", "10:00")]
               for i in range(5))
    future = daily_windows(effect)
    assert future[str(effect)] == [("09:00", "10:00")]
    assert future[str(effect + timedelta(days=1))] == [
        ("11:00", "12:00"), ("13:00", "14:00")]
    assert str(effect + timedelta(days=2)) not in future
    for i in (3, 4):
        assert future[str(effect + timedelta(days=i))] == [("09:00", "10:00")]
    grid = client.get(ROOT, params={"effective_from": str(effect),
                                     "timezone_name": ZONE}).json()
    thursday = next(item for item in grid["sections"]
                    if item["weekday"] == 3 and item["kind"] == "GENERAL")
    assert thursday["slots"][0]["sources"]  # Provenance reste traçable après scission.
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            WeeklyScheduleCommandRecord)) == 1


def test_stale_multi_day_copy_refuses_every_cell_without_partial_mutation(runtime):
    """TP-023C: 409 rejects the entire Tuesday + Wednesday draft."""
    client, factory = runtime
    start = monday()
    rule(client, start, weekdays=(0, 1, 2, 3, 4))
    effect = start + timedelta(days=7)
    body = draft(client, effect, [slot("11:00", "12:00")], weekday=1)
    body["sections"].append({
        "weekday": 2, "kind": "GENERAL", "work_type_id": None,
        "slots": [slot("13:00", "14:00")],
    })
    token = preview(client, body)
    # Another transaction changes the source versions after the preview.
    rule(client, start, weekdays=(6,), begins="15:00", ends="16:00")
    rejected = confirm(client, body, token)
    assert rejected.status_code == 409, rejected.text
    after = occurrences(client, effect)
    assert datetime.fromisoformat(after[str(effect + timedelta(days=1))]).astimezone(
        ZoneInfo(ZONE)).strftime("%H:%M") == "09:00"
    assert datetime.fromisoformat(after[str(effect + timedelta(days=2))]).astimezone(
        ZoneInfo(ZONE)).strftime("%H:%M") == "09:00"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(
            WeeklyScheduleCommandRecord)) == 0


def _categorized_rule(client, effect, work_type_id, *, zone=ZONE, weekday=1,
                      begins="10:00", ends="11:00"):
    result = client.post("/api/availability/rules", json={
        "effective_from": str(effect), "timezone_name": zone,
        "days_of_week": [weekday], "starts_at_local": begins,
        "ends_at_local": ends, "kind": "CATEGORIZED",
        "work_type_id": work_type_id, "mode": "PREFERRED",
    })
    assert result.status_code == 201, result.text
    return result.json()


def test_tp023d_envelope_expansion_and_precise_new_reduction(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    rule(client, effect, weekdays=(1,), begins="09:00", ends="17:00")
    _categorized_rule(client, effect, focus)
    baseline = client.get("/api/availability/effective", params={
        "from": str(effect), "to": str(effect + timedelta(days=7)),
        "timezone_name": ZONE,
    }).json()
    assert not any(item["code"] == "OUTSIDE_GENERAL_ENVELOPE"
                   for item in baseline["issues"])
    enlarged = draft(client, effect, [slot("08:00", "17:00")])
    expanded_preview = preview(client, enlarged)
    assert expanded_preview["invalid_conflicts"] == []
    assert confirm(client, enlarged, expanded_preview).status_code == 200

    reduced = draft(client, effect, [slot("10:30", "17:00")])
    reduced_preview = preview(client, reduced)
    new = [item for item in reduced_preview["invalid_diagnostics"]
           if item["code"] == "OUTSIDE_GENERAL_ENVELOPE"
           and item["status"] == "NEW"]
    assert new and "OUTSIDE_GENERAL_ENVELOPE" in reduced_preview["invalid_conflicts"]
    assert any(item["date"] == str(effect + timedelta(days=1)) and
               item["starts_at"][11:16] == "10:00" and
               item["ends_at"][11:16] == "10:30" and
               item["work_type_id"] == focus and
               item["cause"] == "NO_COVERING_GENERAL"
               for item in new)
    assert confirm(client, reduced, reduced_preview).status_code == 400
    grid = client.get(ROOT, params={
        "effective_from": str(effect), "timezone_name": ZONE,
    }).json()
    general = next(item for item in grid["sections"] if item["kind"] == "GENERAL")
    assert general["slots"][0]["starts_at_local"] == "08:00"


def test_tp023d_improving_preexisting_conflict_never_blocks(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    rule(client, effect, weekdays=(1,), begins="09:00", ends="17:00")
    _categorized_rule(client, effect, focus, begins="07:00", ends="10:00")
    enlarged = draft(client, effect, [slot("08:00", "17:00")])
    token = preview(client, enlarged)
    assert token["invalid_conflicts"] == []
    leftovers = [item for item in token["invalid_diagnostics"]
                 if item["code"] == "OUTSIDE_GENERAL_ENVELOPE"]
    assert leftovers and all(item["status"] == "PREEXISTING" for item in leftovers)
    assert any(item["starts_at"][11:16] == "07:00" and
               item["ends_at"][11:16] == "08:00" for item in leftovers)
    assert confirm(client, enlarged, token).status_code == 200


def test_tp023d_atomic_general_and_category_repair(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    rule(client, effect, weekdays=(1,), begins="09:00", ends="17:00")
    _categorized_rule(client, effect, focus)
    body = draft(client, effect, [slot("10:30", "17:00")])
    body["sections"].append({
        "weekday": 1, "kind": "CATEGORIZED", "work_type_id": focus,
        "slots": [{**slot("10:30", "11:00"), "mode": "PREFERRED"}],
    })
    token = preview(client, body)
    assert token["invalid_conflicts"] == []
    assert not any(item["status"] == "NEW" for item in token["invalid_diagnostics"])
    assert confirm(client, body, token).status_code == 200


def test_tp023d_foreign_timezone_hidden_rule_has_actionable_source(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Focus"}).json()["id"]
    rule(client, effect, weekdays=(1,), begins="08:00", ends="17:00")
    foreign = _categorized_rule(client, effect, focus, zone="UTC",
                                begins="13:00", ends="14:00")
    grid = client.get(ROOT, params={
        "effective_from": str(effect), "timezone_name": ZONE,
    }).json()
    assert not any(item["kind"] == "CATEGORIZED" for item in grid["sections"])
    body = draft(client, effect, [slot("12:00", "17:00")])
    token = preview(client, body)
    matches = [item for item in token["invalid_diagnostics"]
               if item["code"] == "OUTSIDE_GENERAL_ENVELOPE" and
               item["status"] == "NEW" and item["work_type_id"] == focus]
    assert matches
    assert any("UTC" in item["source_timezones"] and
               foreign["id"] in item["rule_ids"] and
               item["timezone_name"] == ZONE for item in matches)
    assert confirm(client, body, token).status_code == 400


def test_tp023d_future_category_another_weekday_is_dated(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Future focus"}).json()["id"]
    rule(client, effect, weekdays=(2,), begins="09:00", ends="17:00")
    _categorized_rule(client, effect + timedelta(days=7), focus, weekday=2)
    body = draft(client, effect, [slot("11:00", "17:00")], weekday=2)
    token = preview(client, body)
    diagnostics = [v for v in token["invalid_diagnostics"]
                   if v["status"] == "NEW" and v["work_type_id"] == focus]
    first_wednesday = effect + timedelta(days=9)
    assert diagnostics and any(v["date"] == str(first_wednesday) and
                               v["starts_at"][11:16] == "10:00" and
                               v["ends_at"][11:16] == "11:00" for v in diagnostics)
    assert confirm(client, body, token).status_code == 400


def test_tp023d_cancelled_general_has_removed_cause_without_fake_new_error(runtime):
    client, _ = runtime
    effect = monday()
    focus = client.post("/api/work-types", json={"name": "Focus exception"}).json()["id"]
    tuesday_general = rule(client, effect, weekdays=(1,), begins="09:00", ends="17:00")
    rule(client, effect, weekdays=(2,), begins="09:00", ends="17:00")
    _categorized_rule(client, effect, focus, weekday=1)
    removed = {
        "action": "CANCEL", "rule_id": tuesday_general["id"],
        "original_local_date": str(effect + timedelta(days=1)),
        "timezone_name": ZONE,
    }
    token = client.post("/api/availability/exceptions/preview", json=removed)
    assert token.status_code == 200, token.text
    saved = client.post("/api/availability/exceptions", json={
        **removed, "expected_fingerprint": token.json()["fingerprint"]})
    assert saved.status_code == 201, saved.text

    body = draft(client, effect, [slot("08:00", "17:00")], weekday=2)
    result = preview(client, body)
    issues = [item for item in result["invalid_diagnostics"]
              if item["code"] == "OUTSIDE_GENERAL_ENVELOPE"]
    assert issues and result["invalid_conflicts"] == []
    assert any(item["cause"] == "REMOVED_BY_EXCEPTION" and
               item["status"] == "PREEXISTING" for item in issues)
    assert confirm(client, body, result).status_code == 200
