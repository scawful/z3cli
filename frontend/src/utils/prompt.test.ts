import test from "node:test";
import assert from "node:assert/strict";

import {
  activeConstructMention,
  activeFileMention,
  buildConstructCandidates,
  buildDraftConstructPreview,
  buildDraftFilePreviews,
  buildFilePreviewMeta,
  buildSpriteCatalogConstructCandidates,
  extractMentionedConstructRefs,
  extractMentionedFiles,
  filterConstructs,
  filterFiles,
  filterPalette,
  searchConstructs,
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
  assert.equal(filterConstructs(candidates, "room", "0x45")[0]?.token, "#room:0x45");
  assert.equal(filtered[0]?.source, "resource labels");
});

test("searchConstructs flags ambiguous top matches", () => {
  const candidates = buildConstructCandidates({
    room: {
      "0x45": "Glacia Estate (Jail Cells)",
      "0x46": "Glade Ruins",
      "0x47": "Zora Temple",
    },
  });

  const result = searchConstructs(candidates, "room", "gla");
  assert.equal(result.ambiguous, true);
  assert.equal(result.totalCount, 2);
  assert.deepEqual(result.matches.map((candidate) => candidate.token), ["#room:0x46", "#room:0x45"]);
});

test("buildDraftConstructPreview enriches attached refs with project metadata", () => {
  const candidates = buildConstructCandidates({
    room: {
      "0x45": "Glacia Estate (Jail Cells)",
    },
  });

  const preview = buildDraftConstructPreview({
    kind: "room",
    query: "0x45",
    token: "#room:0x45",
  }, candidates);

  assert.deepEqual(preview, {
    kind: "room",
    query: "0x45",
    token: "#room:0x45",
    id: "0x45",
    label: "Glacia Estate (Jail Cells)",
    source: "resource labels",
    status: "resolved",
    matchCount: 1,
  });
});

test("buildDraftConstructPreview marks ambiguous typed refs before send", () => {
  const candidates = buildConstructCandidates({
    room: {
      "0x45": "Glacia Estate (Jail Cells)",
      "0x46": "Glade Ruins",
    },
  });

  const preview = buildDraftConstructPreview({
    kind: "room",
    query: "gla",
    token: "#room:gla",
  }, candidates);

  assert.equal(preview.status, "ambiguous");
  assert.equal(preview.matchCount, 2);
  assert.equal(preview.label, "Glade Ruins");
});

test("buildFilePreviewMeta builds multi-line asm previews from meaningful lines", () => {
  const preview = buildFilePreviewMeta("src/room.asm", "; init room\nroomStart:\nlda #$01\nsta $7E0010\n");

  assert.deepEqual(preview, {
    typeLabel: "asm",
    snippet: "roomStart:\nlda #$01",
  });
});

test("buildFilePreviewMeta summarizes root json keys", () => {
  const preview = buildFilePreviewMeta(
    "Docs/Dev/Planning/oracle_resource_labels.json",
    JSON.stringify({ room: {}, sprite: {}, message: {}, music: {}, item: {} }),
  );

  assert.deepEqual(preview, {
    typeLabel: "json",
    snippet: "keys: room, sprite, message, music +1",
  });
});

test("buildFilePreviewMeta summarizes top-level yaml keys", () => {
  const preview = buildFilePreviewMeta(
    "config/settings.yml",
    [
      "# active config",
      "workspace: oracle-of-secrets",
      "models:",
      "  planner: nayru",
      "backend: studio",
      "profiles:",
      "  default: fast",
      "tools: true",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "yaml",
    snippet: "keys: workspace, models, backend, profiles +1",
  });
});

test("buildFilePreviewMeta summarizes toml tables before plain keys", () => {
  const preview = buildFilePreviewMeta(
    "z3dk.toml",
    [
      "name = \"oracle\"",
      "version = \"1\"",
      "[backend]",
      "provider = \"studio\"",
      "[models.plan]",
      "name = \"nayru\"",
      "[[profiles.dev]]",
      "label = \"local\"",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "toml",
    snippet: "tables: backend, models.plan, profiles.dev",
  });
});

test("buildFilePreviewMeta summarizes markdown headings outside code fences", () => {
  const preview = buildFilePreviewMeta(
    "README.md",
    [
      "# Oracle of Secrets",
      "A Zelda hacking workspace for Oracle and ALTTP experiments.",
      "",
      "## Build",
      "```md",
      "# ignored heading",
      "```",
      "## Debugging",
      "## Notes",
      "## Appendix",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "md",
    snippet: "doc: Oracle of Secrets\nsections: Build, Debugging, Notes, Appendix\nA Zelda hacking workspace for Oracle and ALTTP experiments.",
  });
});

test("buildFilePreviewMeta uses markdown frontmatter for doc metadata summaries", () => {
  const preview = buildFilePreviewMeta(
    "docs/guide.md",
    [
      "---",
      "title: Dungeon Hook Notes",
      "status: draft",
      "tags:",
      "  - asm",
      "  - zelda",
      "owner: nayru",
      "project: oracle-of-secrets",
      "slug: dungeon-hook-notes",
      "updated: 2026-04-18",
      "summary: Notes for validating hook callsites.",
      "---",
      "# Fallback Heading",
      "## Checklist",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "md",
    snippet: "doc: Dungeon Hook Notes\nmeta: status=draft · tags=asm, zelda · updated=2026-04-18 · owner=nayru +2\nsections: Fallback Heading, Checklist",
  });
});

test("buildFilePreviewMeta summarizes org titles with TODO and tag rollups", () => {
  const preview = buildFilePreviewMeta(
    "Docs/notes.org",
    [
      "#+title: Debug Notebook",
      "",
      "* TODO Crash triage :bug:",
      "Track the black-screen repro and compare savestates.",
      "* TODO Hooks :asm:",
      "#+begin_src asm",
      "* ignored source heading",
      "#+end_src",
      "* DONE References :docs:",
      "* Follow-up",
      "* Appendix",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "org",
    snippet: "doc: Debug Notebook\ntodo: TODO=2 · DONE=1 · tags=bug, asm, docs\nheadings: Crash triage, Hooks, References, Follow-up +1",
  });
});

test("buildFilePreviewMeta summarizes org property drawers before fallback headings", () => {
  const preview = buildFilePreviewMeta(
    "Docs/handoff.org",
    [
      "#+title: Room Handoff",
      "* Active Issues",
      ":PROPERTIES:",
      ":CREATED: [2026-04-18]",
      ":CUSTOM_ID: room-handoff",
      ":ROM: oos168",
      ":STATUS: active",
      ":END:",
      "Track the remaining room edge cases.",
      "* Follow-up",
    ].join("\n"),
  );

  assert.deepEqual(preview, {
    typeLabel: "org",
    snippet: "doc: Room Handoff\nprops: CREATED=[2026-04-18] · CUSTOM_ID=room-handoff · ROM=oos168 · STATUS=active\nheadings: Active Issues, Follow-up",
  });
});

test("buildDraftFilePreviews enriches files with origin and preview metadata", () => {
  const previews = buildDraftFilePreviews([
    { path: "src/room.asm", lines: 2, chars: 18 },
  ], ["src/room.asm"], {
    "src/room.asm": {
      typeLabel: "asm",
      snippet: "lda #$01",
    },
  });

  assert.deepEqual(previews, [{
    path: "src/room.asm",
    lines: 2,
    chars: 18,
    origin: "picker",
    status: "resolved",
    typeLabel: "asm",
    snippet: "lda #$01",
  }]);
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
    source: "sprite catalog",
    detail: "D6 (Goron Mines) | ✅ Done",
  }]);
});
