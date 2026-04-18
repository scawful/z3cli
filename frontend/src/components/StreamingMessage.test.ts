import test from "node:test";
import assert from "node:assert/strict";

import { resolveStreamingMessageState } from "./StreamingMessage.js";

test("resolveStreamingMessageState keeps live text visible even when transcript messages are hidden", () => {
  const state = resolveStreamingMessageState(
    {
      showThinking: "off",
    },
    "hook at $1abc",
    "",
    null,
  );

  assert.equal(state.plainAnsi.includes("$1abc"), true);
  assert.equal(state.showThinkingIndicator, false);
});

test("resolveStreamingMessageState falls back to the thinking indicator when nothing else is visible", () => {
  const state = resolveStreamingMessageState(
    {
      showThinking: "off",
    },
    "",
    "private trace",
    null,
  );

  assert.equal(state.plainAnsi, "");
  assert.equal(state.visibleThinking, "");
  assert.equal(state.visibleToolCall, null);
  assert.equal(state.showThinkingIndicator, true);
});

test("resolveStreamingMessageState always keeps the active tool call visible", () => {
  const state = resolveStreamingMessageState(
    {
      showThinking: "off",
    },
    "",
    "",
    { name: "read_file", server: "workspace", elapsed: 2 },
  );

  assert.deepEqual(state.visibleToolCall, { name: "read_file", server: "workspace", elapsed: 2 });
  assert.equal(state.showThinkingIndicator, false);
});
