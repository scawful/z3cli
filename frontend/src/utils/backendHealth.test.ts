import test from "node:test";
import assert from "node:assert/strict";

import { shouldShowBackendErrorBanner, backendErrorHint } from "./backendHealth.js";

test("shouldShowBackendErrorBanner hides when there are no errors", () => {
  assert.equal(shouldShowBackendErrorBanner(null), false);
  assert.equal(shouldShowBackendErrorBanner(undefined), false);
  assert.equal(shouldShowBackendErrorBanner({}), false);
  assert.equal(
    shouldShowBackendErrorBanner({ requestErrorCount: 0, requestSuccessCount: 3, lastRequestStatus: "ok" }),
    false,
  );
});

test("shouldShowBackendErrorBanner shows while no request has succeeded", () => {
  assert.equal(
    shouldShowBackendErrorBanner({ requestErrorCount: 1, requestSuccessCount: 0 }),
    true,
  );
});

test("shouldShowBackendErrorBanner shows on a fresh error even after prior success", () => {
  assert.equal(
    shouldShowBackendErrorBanner({ requestErrorCount: 2, requestSuccessCount: 5, lastRequestStatus: "error" }),
    true,
  );
});

test("shouldShowBackendErrorBanner hides once a later success recovers the channel", () => {
  assert.equal(
    shouldShowBackendErrorBanner({ requestErrorCount: 2, requestSuccessCount: 5, lastRequestStatus: "ok" }),
    false,
  );
});

test("shouldShowBackendErrorBanner hides when user has dismissed the current errors", () => {
  assert.equal(
    shouldShowBackendErrorBanner({
      requestErrorCount: 2,
      requestSuccessCount: 0,
      lastRequestStatus: "error",
      dismissedErrorCount: 2,
    }),
    false,
  );
});

test("shouldShowBackendErrorBanner re-opens after dismissal when a new error arrives", () => {
  assert.equal(
    shouldShowBackendErrorBanner({
      requestErrorCount: 5,
      requestSuccessCount: 0,
      lastRequestStatus: "error",
      dismissedErrorCount: 2,
    }),
    true,
  );
});

test("shouldShowBackendErrorBanner treats null dismissal as never-dismissed", () => {
  assert.equal(
    shouldShowBackendErrorBanner({
      requestErrorCount: 1,
      requestSuccessCount: 0,
      dismissedErrorCount: null,
    }),
    true,
  );
});

test("backendErrorHint prefers the first-run hint when nothing has succeeded yet", () => {
  assert.match(
    backendErrorHint({ requestErrorCount: 1, requestSuccessCount: 0 }),
    /no request has succeeded yet/,
  );
});

test("backendErrorHint falls back to a retry hint after prior successes", () => {
  assert.match(
    backendErrorHint({ requestErrorCount: 3, requestSuccessCount: 5, lastRequestStatus: "error" }),
    /last request failed/,
  );
});
