import test from "node:test";
import assert from "node:assert/strict";

import {
  buildThinkingDisplay,
  buildThinkingPreview,
  prefixThinkingLines,
  showStreamingThinking,
  showSubagentThinking,
  showTranscriptThinking,
} from "./thinking.js";

test("reasoning visibility modes separate streaming from transcript rendering", () => {
  assert.equal(showStreamingThinking("off"), false);
  assert.equal(showStreamingThinking("streamed-only"), true);
  assert.equal(showStreamingThinking("transcript"), true);

  assert.equal(showTranscriptThinking("off"), false);
  assert.equal(showTranscriptThinking("streamed-only"), false);
  assert.equal(showTranscriptThinking("transcript"), true);

  assert.equal(showSubagentThinking("off", "running"), false);
  assert.equal(showSubagentThinking("streamed-only", "running"), true);
  assert.equal(showSubagentThinking("streamed-only", "done"), false);
  assert.equal(showSubagentThinking("transcript", "done"), true);
});

test("buildThinkingPreview keeps the first lines for transcript history", () => {
  const preview = buildThinkingPreview("one\ntwo\nthree\nfour\nfive\nsix\nseven", { mode: "head", lineLimit: 4 });

  assert.equal(preview.text, "one\ntwo\nthree\nfour");
  assert.equal(preview.truncated, true);
  assert.equal(preview.overflowLabel, "3 more lines");
  assert.equal(preview.lineCount, 7);
});

test("buildThinkingPreview keeps the newest text for live streaming tails", () => {
  const preview = buildThinkingPreview("alpha beta gamma delta epsilon zeta eta theta", {
    mode: "tail",
    lineLimit: 6,
    charLimit: 18,
  });

  assert.equal(preview.text, "zeta eta theta");
  assert.equal(preview.truncated, true);
  assert.equal(preview.overflowLabel, "27 more chars");
});

test("buildThinkingDisplay expands reasoning fully when detail is full", () => {
  const display = buildThinkingDisplay("one\ntwo\nthree", "full", { mode: "head", lineLimit: 1 });

  assert.equal(display.text, "one\ntwo\nthree");
  assert.equal(display.truncated, false);
  assert.equal(display.lineCount, 3);
});

test("prefixThinkingLines visually separates reasoning lines", () => {
  assert.equal(prefixThinkingLines("alpha\nbeta"), "│ alpha\n│ beta");
});
