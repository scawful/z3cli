import test from "node:test";
import assert from "node:assert/strict";

import {
  activeConstructMention,
  activeFileMention,
  buildConstructCandidates,
  buildSpriteCatalogConstructCandidates,
  extractMentionedConstructRefs,
  extractMentionedFiles,
  filterConstructs,
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

test("activeConstructMention resolves the live #kind:query under the cursor", () => {
  const text = "inspect #room:gla";
  assert.deepEqual(activeConstructMention(text, text.length), {
    start: 8,
    end: text.length,
    kind: "room",
    query: "gla",
  });
  assert.equal(activeConstructMention("inspect #unknown:gla", 20), null);
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

test("extractMentionedConstructRefs deduplicates normalized #refs", () => {
  const text = "inspect #room:0x45 and #room:0x45, then #map:0x1A.";
  assert.deepEqual(extractMentionedConstructRefs(text), [
    { kind: "room", query: "0x45", token: "#room:0x45" },
    { kind: "overworld", query: "0x1A", token: "#overworld:0x1A" },
  ]);
});

test("filterConstructs ranks project label matches within the requested namespace", () => {
  const candidates = buildConstructCandidates({
    room: {
      "0x45": "Glacia Estate (Jail Cells)",
      "0x46": "Zora Temple (Compass Chest)",
    },
    sprite: {
      "0x07": "Village Elder",
    },
  });
  const filtered = filterConstructs(candidates, "room", "glacia");
  assert.equal(filtered[0]?.token, "#room:0x45");
  assert.equal(filterConstructs(candidates, "sprite", "village")[0]?.token, "#sprite:0x07");
});

test("buildSpriteCatalogConstructCandidates exposes object refs from sprite catalog markdown", () => {
  const candidates = buildSpriteCatalogConstructCandidates([
    "## Objects (8 files)",
    "| Sprite | Status | Location | Purpose | Notes |",
    "|--------|--------|----------|---------|-------|",
    "| **Minecart** | ✅ Done | D6 (Goron Mines) | Rideable puzzle system | Complex track persistence |",
  ].join("\n"));

  assert.deepEqual(candidates, [{
    kind: "object",
    query: "minecart",
    id: "minecart",
    label: "Minecart",
    token: "#object:minecart",
    aliases: "object Objects Minecart D6 (Goron Mines) ✅ Done Complex track persistence",
  }]);
});
