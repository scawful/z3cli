import test from "node:test";
import assert from "node:assert/strict";

import { parseCliArgs, shouldSuppressWelcome } from "./cliArgs.js";

test("parseCliArgs forwards unknown flags untouched", () => {
  const parsed = parseCliArgs(["--rom", "path/to/rom.sfc", "--verbose"]);
  assert.deepEqual(parsed.backendArgs, ["--rom", "path/to/rom.sfc", "--verbose"]);
  assert.deepEqual(parsed.startupCommands, []);
});

test("parseCliArgs with --resume and a name pairs them into a startup command", () => {
  const parsed = parseCliArgs(["--resume", "session-20260417"]);
  assert.deepEqual(parsed.backendArgs, []);
  assert.deepEqual(parsed.startupCommands, ["/resume session-20260417"]);
});

test("parseCliArgs with --resume but no name yields a bare command so the picker opens", () => {
  const parsed = parseCliArgs(["--resume"]);
  assert.deepEqual(parsed.backendArgs, []);
  assert.deepEqual(parsed.startupCommands, ["/resume"]);
});

test("parseCliArgs with --resume followed by another flag does not consume the flag", () => {
  const parsed = parseCliArgs(["--resume", "--rom", "path.sfc"]);
  assert.deepEqual(parsed.backendArgs, ["--rom", "path.sfc"]);
  assert.deepEqual(parsed.startupCommands, ["/resume"]);
});

test("parseCliArgs handles --resume=name form", () => {
  const parsed = parseCliArgs(["--resume=yesterday"]);
  assert.deepEqual(parsed.backendArgs, []);
  assert.deepEqual(parsed.startupCommands, ["/resume yesterday"]);
});

test("parseCliArgs preserves backend args on either side of --resume", () => {
  const parsed = parseCliArgs(["--rom", "rom.sfc", "--resume", "last", "--verbose"]);
  assert.deepEqual(parsed.backendArgs, ["--rom", "rom.sfc", "--verbose"]);
  assert.deepEqual(parsed.startupCommands, ["/resume last"]);
});

test("shouldSuppressWelcome is false for empty or unrelated commands", () => {
  assert.equal(shouldSuppressWelcome([]), false);
  assert.equal(shouldSuppressWelcome(["/help", "hello"]), false);
});

test("shouldSuppressWelcome is true when /resume is queued", () => {
  assert.equal(shouldSuppressWelcome(["/resume"]), true);
  assert.equal(shouldSuppressWelcome(["/resume session-a"]), true);
  assert.equal(shouldSuppressWelcome(["  /resume foo  "]), true);
});

test("shouldSuppressWelcome is true when /resume appears alongside other commands", () => {
  assert.equal(shouldSuppressWelcome(["hello", "/resume last"]), true);
});
