import test from "node:test";
import assert from "node:assert/strict";

import {
  KEYBOARD_LEGEND_ITEMS,
  classifyPromptSubmission,
  shouldEnableStreamingCancelHotkeys,
} from "./App.js";

test("classifyPromptSubmission keeps attachment-only prompts sendable", () => {
  assert.deepEqual(
    classifyPromptSubmission("   ", [{ path: "src/room.asm", lines: 0, chars: 0 }]),
    {
      kind: "message",
      text: "",
      attachments: [{ path: "src/room.asm", lines: 0, chars: 0 }],
      constructRefs: [],
    },
  );
});

test("classifyPromptSubmission keeps construct-only prompts sendable", () => {
  assert.deepEqual(
    classifyPromptSubmission("   ", [], [{ kind: "room", query: "0x45", token: "#room:0x45" }]),
    {
      kind: "message",
      text: "",
      attachments: [],
      constructRefs: [{ kind: "room", query: "0x45", token: "#room:0x45" }],
    },
  );
});

test("classifyPromptSubmission ignores empty prompts without attachments", () => {
  assert.deepEqual(classifyPromptSubmission("   "), { kind: "ignore" });
});

test("classifyPromptSubmission splits slash commands into cmd and args", () => {
  assert.deepEqual(
    classifyPromptSubmission(" /backend studio "),
    { kind: "command", cmd: "/backend", args: ["studio"] },
  );
});

test("shouldEnableStreamingCancelHotkeys stays active during normal streaming", () => {
  assert.equal(
    shouldEnableStreamingCancelHotkeys({
      isStreaming: true,
      rawModeSupported: true,
      settingsOpen: false,
      helpOpen: false,
      modelManagerOpen: false,
      hasPendingPermission: false,
      hasPendingReview: false,
    }),
    true,
  );
});

test("shouldEnableStreamingCancelHotkeys disables global cancel while a modal is open", () => {
  assert.equal(
    shouldEnableStreamingCancelHotkeys({
      isStreaming: true,
      rawModeSupported: true,
      settingsOpen: false,
      helpOpen: false,
      modelManagerOpen: false,
      hasPendingPermission: true,
      hasPendingReview: false,
    }),
    false,
  );
  assert.equal(
    shouldEnableStreamingCancelHotkeys({
      isStreaming: true,
      rawModeSupported: true,
      settingsOpen: false,
      helpOpen: false,
      modelManagerOpen: true,
      hasPendingPermission: false,
      hasPendingReview: false,
    }),
    false,
  );
  assert.equal(
    shouldEnableStreamingCancelHotkeys({
      isStreaming: true,
      rawModeSupported: true,
      settingsOpen: false,
      helpOpen: false,
      modelManagerOpen: false,
      hasPendingPermission: false,
      hasPendingReview: true,
    }),
    false,
  );
});

test("keyboard legend keeps only the compact core shortcuts", () => {
  assert.deepEqual(
    KEYBOARD_LEGEND_ITEMS,
    [
      { key: "[Ctrl+P]", label: "Palette" },
      { key: "[Tab]", label: "Complete" },
      { key: "[Shift+Tab]", label: "Mode" },
    ],
  );
});
