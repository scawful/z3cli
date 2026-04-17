import test from "node:test";
import assert from "node:assert/strict";

import {
  cacheHitRate,
  estimatedSavingsCents,
  formatCacheCompact,
} from "./cacheMetrics.js";

test("cacheHitRate returns 0 when both inputs are 0", () => {
  assert.equal(cacheHitRate(0, 0), 0);
});

test("cacheHitRate is 1 for pure reads and 0 for pure writes", () => {
  assert.equal(cacheHitRate(500, 0), 1);
  assert.equal(cacheHitRate(0, 500), 0);
});

test("cacheHitRate handles mixed totals", () => {
  // 900 reads + 100 creations => 0.9
  assert.equal(cacheHitRate(900, 100), 0.9);
  assert.equal(cacheHitRate(3, 1), 0.75);
});

test("formatCacheCompact returns empty string when no activity", () => {
  assert.equal(formatCacheCompact(0, 0), "");
});

test("formatCacheCompact shows caching-on state before any reads", () => {
  const text = formatCacheCompact(0, 1200);
  assert.ok(text.startsWith("caching on"), `got: ${text}`);
  assert.ok(text.includes("1.2k"), `got: ${text}`);
});

test("formatCacheCompact shows hit rate and total once reads happen", () => {
  // 9400 reads + 600 creation => 94% hit, 10.0k total
  const text = formatCacheCompact(9400, 600);
  assert.ok(text.includes("94% hit"), `got: ${text}`);
  assert.ok(text.includes("cached"), `got: ${text}`);
  assert.ok(text.includes("10.0k"), `got: ${text}`);
});

test("estimatedSavingsCents is positive when reads dominate", () => {
  // 1M reads, 0 creation @ $3/M input => saves 0.9 * $3 = $2.70 => 270c
  const cents = estimatedSavingsCents(1_000_000, 0, 0, 3.0);
  assert.ok(cents > 0, `expected positive, got ${cents}`);
  assert.ok(Math.abs(cents - 270) < 0.0001, `expected 270c, got ${cents}`);
});

test("estimatedSavingsCents is negative when creation dominates", () => {
  // 0 reads, 1M creation @ $3/M => 0 - 0.25 * $3 = -$0.75 => -75c
  const cents = estimatedSavingsCents(0, 1_000_000, 0, 3.0);
  assert.ok(cents < 0, `expected negative, got ${cents}`);
  assert.ok(Math.abs(cents + 75) < 0.0001, `expected -75c, got ${cents}`);
});
