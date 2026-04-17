import test from "node:test";
import assert from "node:assert/strict";

import { cancelRequestTarget, evaluateRequestScope } from "./requestScope.js";

test("evaluateRequestScope adopts the first request id and rejects mismatches", () => {
  let active = "";

  const first = evaluateRequestScope(active, "req-2");
  active = first.nextActiveRequestId;
  assert.equal(first.accept, true);
  assert.equal(active, "req-2");

  const outOfOrder = evaluateRequestScope(active, "req-1");
  assert.equal(outOfOrder.accept, false);
  assert.equal(outOfOrder.nextActiveRequestId, "req-2");

  const sameRequest = evaluateRequestScope(active, "req-2");
  assert.equal(sameRequest.accept, true);
});

test("evaluateRequestScope allows request-less events without changing scope", () => {
  const seeded = evaluateRequestScope("req-7", "");
  assert.equal(seeded.accept, true);
  assert.equal(seeded.nextActiveRequestId, "req-7");

  const unknown = evaluateRequestScope("req-7", undefined);
  assert.equal(unknown.accept, true);
  assert.equal(unknown.nextActiveRequestId, "req-7");
});

test("cancelRequestTarget only returns active request ids", () => {
  assert.equal(cancelRequestTarget(""), undefined);
  assert.equal(cancelRequestTarget("req-9"), "req-9");
});

