import test from "node:test";
import assert from "node:assert/strict";

import { buildSubagentPreview, buildSubagentThinkingPreview } from "./SubagentPanel.js";

test("buildSubagentPreview keeps the newest lines while a subagent is running", () => {
  const preview = buildSubagentPreview(
    "one\ntwo\nthree\nfour\nfive\nsix",
    "running",
  );

  assert.equal(preview.text, "three\nfour\nfive\nsix");
  assert.equal(preview.truncated, true);
  assert.equal(preview.overflowLabel, "2 more lines");
});

test("buildSubagentPreview caps completed subagents to the opening summary lines", () => {
  const preview = buildSubagentPreview(
    "summary line 1\nsummary line 2\nsummary line 3\nsummary line 4\nverbose tail 5\nverbose tail 6",
    "done",
  );

  assert.equal(
    preview.text,
    "summary line 1\nsummary line 2\nsummary line 3\nsummary line 4",
  );
  assert.equal(preview.truncated, true);
  assert.equal(preview.overflowLabel, "2 more lines");
});

test("buildSubagentPreview truncates a long single-line summary", () => {
  const longLine = "summary ".repeat(60).trim();
  const preview = buildSubagentPreview(longLine, "done");

  assert.equal(preview.truncated, true);
  assert.ok(preview.text.length <= 240);
  assert.match(preview.overflowLabel ?? "", /more chars/);
});

test("buildSubagentThinkingPreview shows running reasoning tails in preview mode", () => {
  const preview = buildSubagentThinkingPreview(
    "step one\nstep two\nstep three\nstep four\nstep five",
    "running",
    "preview",
  );

  assert.equal(preview.text, "step two\nstep three\nstep four\nstep five");
  assert.equal(preview.truncated, true);
  assert.equal(preview.overflowLabel, "1 more lines");
});

test("buildSubagentThinkingPreview expands full reasoning when requested", () => {
  const preview = buildSubagentThinkingPreview("alpha\nbeta\ngamma", "done", "full");

  assert.equal(preview.text, "alpha\nbeta\ngamma");
  assert.equal(preview.truncated, false);
});
