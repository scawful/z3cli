import test from "node:test";
import assert from "node:assert/strict";

import {
  activeFileMention,
  extractMentionedFiles,
  filterFiles,
  filterPalette,
  scoreFileMatch,
  sessionSlug,
} from "./prompt.js";

test("sessionSlug falls back to hh:mm for microsecond-only session names", () => {
  assert.equal(sessionSlug("2026-04-13_194259_059316"), "19:42");
  assert.equal(sessionSlug("2026-04-13_194259_059316_fix-resume"), "fix-resume");
});

test("activeFileMention resolves the live @query under the cursor", () => {
  const text = "inspect @frontend/src/Pr";
  assert.deepEqual(activeFileMention(text, text.length), {
    start: 8,
    end: text.length,
    query: "frontend/src/Pr",
  });
  assert.equal(activeFileMention("inspect frontend/src/Pr", 23), null);
});

test("filterFiles prioritizes basename and prefix matches", () => {
  const files = [
    "frontend/src/components/PromptInput.tsx",
    "frontend/src/components/PermissionDialog.tsx",
    "z3cli/app/serve.py",
  ];
  const filtered = filterFiles(files, "pr");
  assert.equal(filtered[0], "frontend/src/components/PromptInput.tsx");
  const promptScore = scoreFileMatch("frontend/src/components/PromptInput.tsx", "prompt");
  const permissionScore = scoreFileMatch("frontend/src/components/PermissionDialog.tsx", "prompt");
  assert.notEqual(promptScore, null);
  if (permissionScore !== null) {
    assert.ok(promptScore! < permissionScore);
  }
});

test("filterPalette matches actions by aliases and description", () => {
  const entries = [
    { key: "sessions", label: "Sessions", description: "Browse saved sessions", command: "/sessions", aliases: "resume history" },
    { key: "status", label: "Status", description: "Show runtime state", command: "/status", aliases: "info" },
  ];
  const filtered = filterPalette(entries, "resume");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.command, "/sessions");
});

test("extractMentionedFiles only keeps known workspace matches once", () => {
  const files = ["src/main.asm", "src/room.asm"];
  const text = "inspect @src/main.asm and @src/main.asm, then @src/room.asm.";
  assert.deepEqual(extractMentionedFiles(text, files), ["src/main.asm", "src/room.asm"]);
});
