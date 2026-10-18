import assert from "node:assert/strict";
import { test } from "node:test";
import { toWindowPreviewRequest, validateWindowDraft } from
  "../src/availability-setup/model.ts";

const parents = [{ id: "parent", label: "Travail" }, { id: "other", label: "Personnel" }];
const workTypes = [{ id: "focus", parentId: "parent", label: "Focus" },
  { id: "personal", parentId: "other", label: "Maison" }];
const valid = {
  parentId: "parent", workTypeId: "focus", daysOfWeek: [1, 3],
  startTime: "09:00", endTime: "11:30", priority: "",
  timezone: "America/Toronto", effectiveDate: "2026-10-20",
};
const check = (patch = {}, envelope = ["parent"]) => validateWindowDraft(
  { ...valid, ...patch }, parents, workTypes, envelope, "2026-10-19");

test("valid input, overlap-neutral priority and sorted days are only a preview draft", () => {
  assert.deepEqual(check(), {});
  assert.deepEqual(toWindowPreviewRequest({ ...valid, daysOfWeek: [3, 1] }), {
    ...valid, priority: null, daysOfWeek: [1, 3],
  });
  assert.equal(toWindowPreviewRequest({ ...valid, priority: "2" }).priority, 2);
});

test("no parent, leaf or physical envelope cannot pass local prerequisites", () => {
  assert.ok(check({ parentId: "", workTypeId: "" }).parentId);
  assert.ok(check({ parentId: "parent", workTypeId: "personal" }).workTypeId);
  assert.ok(check({}, []).parentId);
});

test("validates at least one unique weekday and local-time ordering", () => {
  assert.ok(check({ daysOfWeek: [] }).daysOfWeek);
  assert.ok(check({ daysOfWeek: [1, 1] }).daysOfWeek);
  assert.ok(check({ daysOfWeek: [7] }).daysOfWeek);
  assert.ok(check({ startTime: "23:00", endTime: "01:00" }).endTime);
  assert.ok(check({ startTime: "12:00", endTime: "12:00" }).endTime);
  assert.ok(check({ startTime: "29:00" }).startTime);
});

test("priority is optional or a positive integer, never a hidden default", () => {
  for (const bad of ["0", "-2", "1.5", "abc", "9007199254740992"]) {
    assert.ok(check({ priority: bad }).priority, bad);
  }
  assert.deepEqual(check({ priority: "10" }), {});
});

test("rejects invalid IANA zones and invalid or premature civil dates", () => {
  assert.ok(check({ timezone: "Mars/Base" }).timezone);
  assert.ok(check({ effectiveDate: "2026-02-30" }).effectiveDate);
  assert.ok(check({ effectiveDate: "2026-10-18" }).effectiveDate);
  assert.deepEqual(check({ effectiveDate: "2026-10-19" }), {});
});
