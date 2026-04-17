import test from "node:test";
import assert from "node:assert/strict";

import { classifyPromptSubmission } from "./App.js";

test("classifyPromptSubmission keeps attachment-only prompts sendable", () => {
  assert.deepEqual(
    classifyPromptSubmission("   ", [{ path: "src/room.asm" }]),
    {
      kind: "message",
      text: "",
      attachments: [{ path: "src/room.asm" }],
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
