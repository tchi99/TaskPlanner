import test from "node:test";
import assert from "node:assert/strict";
import { setAccessToken, clearAccessToken, getAccessToken } from "../src/token.ts";

test("logout immediately removes the bearer from memory", () => {
  setAccessToken("short-lived-access-token");
  assert.equal(getAccessToken(), "short-lived-access-token");
  clearAccessToken();
  assert.equal(getAccessToken(), null);
});
