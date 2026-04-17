import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  buildToolPreview,
  collapseToolResult,
  parseToolArguments,
  summarizeToolInvocation,
  summarizeToolResult,
} from "./tooling.js";

test("parseToolArguments returns null for invalid JSON", () => {
  assert.equal(parseToolArguments("{oops"), null);
});

test("summarizeToolInvocation prefers target paths and edit counts", () => {
  assert.equal(
    summarizeToolInvocation("edit_file", {
      path: "src/main.ts",
      edits: [{ oldText: "a", newText: "b" }, { oldText: "c", newText: "d" }],
    }),
    "src/main.ts · 2 edits",
  );
});

test("buildToolPreview renders edit previews with +/- lines", async () => {
  const preview = await buildToolPreview(
    "edit_file",
    JSON.stringify({
      path: "src/main.ts",
      edits: [{ oldText: "const a = 1;\n", newText: "const a = 2;\n" }],
    }),
    process.cwd(),
  );
  assert.ok(preview);
  assert.equal(preview?.targetPath, "src/main.ts");
  assert.ok(preview?.lines.some((line) => line.kind === "remove" && line.text.includes("const a = 1")));
  assert.ok(preview?.lines.some((line) => line.kind === "add" && line.text.includes("const a = 2")));
});

test("buildToolPreview reads the previous file for whole-file writes", async () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-tool-preview-"));
  const target = path.join(workspace, "notes.txt");
  fs.writeFileSync(target, "before\n", "utf8");
  try {
    const preview = await buildToolPreview(
      "write_file",
      JSON.stringify({ path: "notes.txt", content: "after\n" }),
      workspace,
    );
    assert.ok(preview?.lines.some((line) => line.kind === "remove" && line.text.includes("before")));
    assert.ok(preview?.lines.some((line) => line.kind === "add" && line.text.includes("after")));
  } finally {
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("summarizeToolResult and collapseToolResult keep long output compact", () => {
  // 7 lines is below the collapse threshold — should not collapse
  const shortContent = ["line 1", "line 2", "line 3", "line 4", "line 5", "line 6", "line 7"].join("\n");
  assert.equal(summarizeToolResult(shortContent), "7 lines · line 1");
  const notCollapsed = collapseToolResult(shortContent);
  assert.equal(notCollapsed.wasCollapsed, false);
  assert.equal(notCollapsed.hiddenLines, 0);
  assert.equal(notCollapsed.truncatedByChars, false);

  // 25 lines exceeds the 20-line limit — should collapse
  const longContent = Array.from({ length: 25 }, (_, i) => `line ${i + 1}`).join("\n");
  const collapsed = collapseToolResult(longContent);
  assert.equal(collapsed.wasCollapsed, true);
  assert.equal(collapsed.hiddenLines, 5);
  assert.equal(collapsed.truncatedByChars, false);
  // display contains only the first 20 lines; the indicator is rendered by MessageBubble
  assert.ok(!collapsed.display.includes("more lines"));
  assert.equal(collapsed.display.split("\n").length, 20);
});

test("collapseToolResult truncates oversized single-line output by chars", () => {
  const hugeLine = "x".repeat(2200);
  const collapsed = collapseToolResult(hugeLine);
  assert.equal(collapsed.wasCollapsed, true);
  assert.equal(collapsed.hiddenLines, 0);
  assert.equal(collapsed.truncatedByChars, true);
  assert.equal(collapsed.display.length, 1500);
});
