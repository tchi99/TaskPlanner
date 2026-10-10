import test from "node:test";
import assert from "node:assert/strict";
import { validApiOrigin, resolveApiUrl } from "../src/api-url.ts";

test("production refuses absent or malformed API origin", () => {
  for (const origin of [undefined, "", "http://api.example.com", "https://user:secret@api.example.com",
    "https://api.example.com/path", "https://api.example.com/?key=token",
    "https://api.example.com/#fragment", "javascript:alert(1)"]) {
    assert.equal(validApiOrigin(origin, true), false, String(origin));
    assert.throws(() => resolveApiUrl("/api/tasks", origin, true));
  }
});

test("production resolves only API paths against fixed HTTPS origin", () => {
  const origin = "https://taskplanner-api.onrender.com";
  assert.equal(resolveApiUrl("/api/tasks?status=INBOX", origin, true),
    origin + "/api/tasks?status=INBOX");
  assert.equal(resolveApiUrl("/api/health", origin, true), origin + "/api/health");
  for (const path of ["https://evil.example/api/tasks", "//evil.example/api/tasks",
    "/not-api", "/api/../openapi.json", "/api/%2e%2e/secret", "/api\\bad",
    "/api\n/foo"]) {
    assert.throws(() => resolveApiUrl(path, origin, true), path);
  }
});

test("local Vite proxy remains valid only outside production", () => {
  assert.equal(resolveApiUrl("/api/tasks", undefined, false), "/api/tasks");
  assert.equal(resolveApiUrl("/api/tasks", "http://localhost:8000", false),
    "http://localhost:8000/api/tasks");
});
