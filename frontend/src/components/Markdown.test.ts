import test from "node:test";
import assert from "node:assert/strict";

import { sanitizeMarkdownForTerminal } from "./Markdown.js";

test("sanitizeMarkdownForTerminal strips unsupported asm fence labels", () => {
  const markdown = [
    "before",
    "```asm",
    "lda #$01",
    "```",
    "after",
  ].join("\n");

  const sanitized = sanitizeMarkdownForTerminal(markdown);
  assert.equal(sanitized.includes("```asm"), false);
  assert.equal(sanitized.includes("lda #$01"), true);
});

test("sanitizeMarkdownForTerminal preserves supported fence labels", () => {
  const markdown = [
    "```json",
    "{\"ok\":true}",
    "```",
  ].join("\n");

  const sanitized = sanitizeMarkdownForTerminal(markdown);
  assert.equal(sanitized, markdown);
});
