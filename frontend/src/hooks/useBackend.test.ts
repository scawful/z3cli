import test from "node:test";
import assert from "node:assert/strict";

import { parsePendingPermission } from "./useBackend.js";

test("parsePendingPermission copies the core identity fields", () => {
  const parsed = parsePendingPermission({
    name: "edit_file",
    server: "afs",
    arguments: '{"path":"src/main.asm"}',
  });
  assert.equal(parsed.name, "edit_file");
  assert.equal(parsed.server, "afs");
  assert.equal(parsed.arguments, '{"path":"src/main.asm"}');
});

test("parsePendingPermission preserves reason when backend includes one", () => {
  const parsed = parsePendingPermission({
    name: "edit_file",
    server: "afs",
    arguments: "{}",
    reason: "subagent [nayru] · write tool: will modify main.asm",
  });
  assert.equal(parsed.reason, "subagent [nayru] · write tool: will modify main.asm");
});

test("parsePendingPermission omits reason when backend sends no field", () => {
  const parsed = parsePendingPermission({
    name: "read_file",
    server: "afs",
    arguments: "{}",
  });
  assert.equal(Object.prototype.hasOwnProperty.call(parsed, "reason"), false);
});

test("parsePendingPermission omits reason for an empty string", () => {
  const parsed = parsePendingPermission({
    name: "read_file",
    server: "afs",
    arguments: "{}",
    reason: "",
  });
  assert.equal(Object.prototype.hasOwnProperty.call(parsed, "reason"), false);
});
