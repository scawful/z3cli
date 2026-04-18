import test from "node:test";
import assert from "node:assert/strict";

import { renderExitBanner, resumeNameFromSessionPath } from "./exitBanner.js";

test("resumeNameFromSessionPath strips directory and .jsonl suffix", () => {
  assert.equal(
    resumeNameFromSessionPath("/Users/x/.z3cli/sessions/2026-04-17_101112_abc_fix.jsonl"),
    "2026-04-17_101112_abc_fix",
  );
  assert.equal(resumeNameFromSessionPath(""), "");
  assert.equal(resumeNameFromSessionPath("bare_name"), "bare_name");
});

test("renderExitBanner includes model, totals, and resume command", () => {
  const output = renderExitBanner({
    model: "din",
    sessionPath: "/tmp/sessions/2026-04-17_101112_demo.jsonl",
    messageCount: 4,
    promptTokens: 1200,
    completionTokens: 800,
    cacheReadTokens: 1800,
    cacheCreationTokens: 200,
    durationMs: 185_000,
  });

  assert.match(output, /Session ended/);
  assert.match(output, /model\s+din/);
  assert.match(output, /messages\s+4/);
  assert.match(output, /tokens\s+2\.0k/);
  assert.match(output, /cache\s+90% hit/);
  assert.match(output, /duration\s+3m 5s/);
  assert.match(output, /z3cli \/resume 2026-04-17_101112_demo/);
});

test("renderExitBanner falls back when there is no session file", () => {
  const output = renderExitBanner({
    model: "",
    sessionPath: "",
    messageCount: 0,
    promptTokens: 0,
    completionTokens: 0,
    cacheReadTokens: 0,
    cacheCreationTokens: 0,
    durationMs: 0,
  });

  assert.match(output, /No session file was saved/);
  assert.match(output, /cache\s+— hit/);
  assert.match(output, /model\s+\(unknown\)/);
});
