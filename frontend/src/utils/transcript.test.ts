import test from "node:test";
import assert from "node:assert/strict";

import type { Message } from "../ipc/protocol.js";
import {
  computeContextPanelLayout,
  BACKEND_ERROR_BANNER_RESERVED_ROWS,
  computeTranscriptViewportHeight,
  filterMessageGroups,
  groupMessages,
  isReasoningCollapseHotkey,
  isTranscriptMessageVisible,
  shouldShowContextPanel,
  shouldShowKeyboardLegend,
  shouldShowKeyHintBar,
  CONTEXT_PANEL_COMPACT_COLUMNS,
  CONTEXT_PANEL_WIDE_COLUMNS,
  TRANSCRIPT_MIN_VIEWPORT_HEIGHT,
} from "./transcript.js";

test("groupMessages keeps tool activity inside the originating turn", () => {
  const messages: Message[] = [
    { id: "u1", role: "user", content: "inspect this", timestamp: 1, turnId: "turn-1" },
    { id: "a1", role: "assistant", content: "checking", timestamp: 2, turnId: "turn-1", model: "nayru" },
    { id: "t1", role: "tool", content: "", timestamp: 3, turnId: "turn-1", toolGroup: "call-1", toolName: "read_file" },
    { id: "t2", role: "tool", content: "ok", timestamp: 4, turnId: "turn-1", toolGroup: "call-1", toolName: "read_file" },
    { id: "u2", role: "user", content: "next", timestamp: 5, turnId: "turn-2" },
  ];

  const grouped = groupMessages(messages);
  assert.equal(grouped.length, 2);
  assert.equal(grouped[0]?.messages.length, 4);
  assert.equal(grouped[1]?.turnId, "turn-2");
});

test("isTranscriptMessageVisible keeps assistant replies visible separately from reasoning", () => {
  const assistant: Message = {
    id: "a1",
    role: "assistant",
    content: "visible answer",
    thinking: "private chain",
    timestamp: 1,
  };

  assert.equal(isTranscriptMessageVisible(assistant, {
    showReasoning: false,
  }), true);
  assert.equal(isTranscriptMessageVisible(assistant, {
    showReasoning: true,
  }), true);
  assert.equal(isTranscriptMessageVisible(assistant, {
    showReasoning: false,
  }), true);
});

test("filterMessageGroups keeps transcript messages while still preserving reasoning-only assistant entries", () => {
  const grouped = groupMessages([
    { id: "u1", role: "user", content: "inspect this", timestamp: 1, turnId: "turn-1" },
    { id: "a1", role: "assistant", content: "", thinking: "reasoning only", timestamp: 2, turnId: "turn-1" },
    { id: "t1", role: "tool", content: "tool output", timestamp: 3, turnId: "turn-1", toolName: "read_file" },
  ]);

  const filtered = filterMessageGroups(grouped, {
    showReasoning: true,
  });

  assert.equal(filtered.length, 1);
  assert.deepEqual(filtered[0]?.messages.map((message) => message.id), ["u1", "a1", "t1"]);
});

test("assistant replies stay visible alongside the rest of the turn", () => {
  const grouped = groupMessages([
    { id: "u1", role: "user", content: "inspect this", timestamp: 1, turnId: "turn-1" },
    { id: "a1", role: "assistant", content: "here is the fix", timestamp: 2, turnId: "turn-1" },
  ]);

  const filtered = filterMessageGroups(grouped, {
    showReasoning: false,
  });

  assert.equal(filtered.length, 1);
  assert.deepEqual(filtered[0]?.messages.map((message) => message.id), ["u1", "a1"]);
});

test("isReasoningCollapseHotkey only keeps the Ctrl+R shortcut", () => {
  assert.equal(isReasoningCollapseHotkey("r", { ctrl: true }), true);
  assert.equal(isReasoningCollapseHotkey("\x12", { ctrl: false }), true);
  assert.equal(isReasoningCollapseHotkey("r", { ctrl: false }), false);
  assert.equal(isReasoningCollapseHotkey("m", { ctrl: false }), false);
});

test("shouldShowContextPanel hides when settings open or terminal too narrow", () => {
  assert.equal(shouldShowContextPanel(160, false), true);
  assert.equal(shouldShowContextPanel(120, false), true);
  assert.equal(shouldShowContextPanel(100, false), false);
  assert.equal(shouldShowContextPanel(160, true), false);
});

test("computeContextPanelLayout picks compact rail for medium terminals and wide rail for large", () => {
  const narrow = computeContextPanelLayout(100, false);
  assert.equal(narrow.visible, false);
  assert.equal(narrow.width, 0);

  const medium = computeContextPanelLayout(130, false);
  assert.equal(medium.visible, true);
  assert.equal(medium.width, CONTEXT_PANEL_COMPACT_COLUMNS);

  const wide = computeContextPanelLayout(170, false);
  assert.equal(wide.visible, true);
  assert.equal(wide.width, CONTEXT_PANEL_WIDE_COLUMNS);

  const settings = computeContextPanelLayout(170, true);
  assert.equal(settings.visible, false);
});

test("shouldShowKeyboardLegend hides the legend on short terminals", () => {
  assert.equal(shouldShowKeyboardLegend(30), true);
  assert.equal(shouldShowKeyboardLegend(22), true);
  assert.equal(shouldShowKeyboardLegend(20), false);
});

test("computeTranscriptViewportHeight reclaims a row when the legend is hidden", () => {
  const withLegend = computeTranscriptViewportHeight(30, true);
  const withoutLegend = computeTranscriptViewportHeight(30, false);
  assert.equal(withoutLegend - withLegend, 1);
  assert.equal(computeTranscriptViewportHeight(5, true), TRANSCRIPT_MIN_VIEWPORT_HEIGHT);
});

test("computeTranscriptViewportHeight accounts for backend error banner rows", () => {
  const normal = computeTranscriptViewportHeight(40, true, false);
  const withBanner = computeTranscriptViewportHeight(40, true, true);
  assert.equal(withBanner, normal - BACKEND_ERROR_BANNER_RESERVED_ROWS);
});

test("shouldShowKeyHintBar requires rows, width, and no open modal", () => {
  const ok = { rows: 30, width: 120, modalOpen: false };
  assert.equal(shouldShowKeyHintBar(ok), true);

  assert.equal(shouldShowKeyHintBar({ ...ok, rows: 20 }), false);
  assert.equal(shouldShowKeyHintBar({ ...ok, width: 79 }), false);
  assert.equal(shouldShowKeyHintBar({ ...ok, modalOpen: true }), false);
});
