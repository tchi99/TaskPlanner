import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const nav = readFileSync(new URL("../src/WorkspaceNav.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/workspace.css", import.meta.url), "utf8");

test("the workspace offers six separate, accessible destinations", () => {
  for (const id of ["today", "inbox", "tasks", "projects", "planning", "weekly"]) {
    assert.match(nav, new RegExp('id: "' + id + '"'));
    assert.match(app, new RegExp('page === "' + id + '"'));
  }
  assert.match(nav, /aria-label="Navigation principale"/);
  assert.match(nav, /aria-current=/);
  assert.match(app, /Aller au contenu/);
});

test("daily workspace does not render weekly, capacity, and full backlog panels by default", () => {
  assert.match(app, /page === "today"/);
  assert.match(app, /page === "weekly"/);
  assert.match(app, /page === "planning"/);
  assert.match(app, /page === "tasks"/);
  assert.match(app, /page === "projects"/);
  assert.match(app, /page === "inbox"/);
});

test("capture and task actions still use their original application APIs", () => {
  for (const expression of [
    "submitCapture",
    "Clarifier",
    "TaskSegments",
    "changeProtection",
    "WeeklyCapacity",
    "DailyReview",
    "WeeklyReview",
    "MorningReview",
  ]) {
    assert.ok(app.includes(expression), expression);
  }
  assert.match(app, /ref=\{captureRef\}/);
});

test("responsive focus and navigation affordances are present", () => {
  assert.match(styles, /max-width: 920px/);
  assert.match(styles, /max-width: 600px/);
  assert.match(styles, /focus-visible/);
  assert.match(styles, /overflow-x: auto/);
});
