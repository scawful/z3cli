import test from "node:test";
import assert from "node:assert/strict";

import {
  chunkLooksLikeMouseEvent,
  parseMouseWheelEvents,
  parseMouseWheelEventsWithCarry,
} from "./mouseEvents.js";

test("parseMouseWheelEvents ignores non-mouse input", () => {
  assert.deepEqual(parseMouseWheelEvents(""), []);
  assert.deepEqual(parseMouseWheelEvents("hello"), []);
  assert.deepEqual(parseMouseWheelEvents("\x1b[A"), []);
});

test("parseMouseWheelEvents decodes wheel-up and wheel-down", () => {
  const events = parseMouseWheelEvents("\x1b[<64;10;5M\x1b[<65;10;6M");
  assert.deepEqual(events, [
    { kind: "wheel-up", col: 10, row: 5, modifiers: { shift: false, alt: false, ctrl: false } },
    { kind: "wheel-down", col: 10, row: 6, modifiers: { shift: false, alt: false, ctrl: false } },
  ]);
});

test("parseMouseWheelEvents ignores click events and release events", () => {
  const clicks = parseMouseWheelEvents("\x1b[<0;5;5M\x1b[<0;5;5m");
  assert.deepEqual(clicks, []);
});

test("parseMouseWheelEvents handles modifier bits mixed with wheel codes", () => {
  // button 80 = wheel-up + Ctrl
  const events = parseMouseWheelEvents("\x1b[<80;12;7M");
  assert.deepEqual(events, [{
    kind: "wheel-up",
    col: 12,
    row: 7,
    modifiers: { shift: false, alt: false, ctrl: true },
  }]);
});

test("parseMouseWheelEventsWithCarry handles split wheel chunks", () => {
  const first = parseMouseWheelEventsWithCarry("\x1b[<64;10;5", "");
  assert.deepEqual(first.events, []);
  assert.equal(first.passthrough, "");
  assert.equal(first.carry, "\x1b[<64;10;5");

  const second = parseMouseWheelEventsWithCarry("M\x1b[<72;2;1M", first.carry);
  assert.deepEqual(second.events, [
    { kind: "wheel-up", col: 10, row: 5, modifiers: { shift: false, alt: false, ctrl: false } },
    { kind: "wheel-up", col: 2, row: 1, modifiers: { shift: false, alt: true, ctrl: false } },
  ]);
  assert.equal(second.passthrough, "");
  assert.equal(second.carry, "");
});

test("parseMouseWheelEventsWithCarry removes complete mouse sequences from passthrough text", () => {
  const parsed = parseMouseWheelEventsWithCarry(
    "ab\x1b[<64;10;5Mcd\x1b[<0;10;5Mef\x1b[<0;10;5mgh",
    "",
  );

  assert.deepEqual(parsed.events, [
    { kind: "wheel-up", col: 10, row: 5, modifiers: { shift: false, alt: false, ctrl: false } },
  ]);
  assert.equal(parsed.passthrough, "abcdefgh");
  assert.equal(parsed.carry, "");
});

test("parseMouseWheelEventsWithCarry preserves non-mouse text around a split mouse chunk", () => {
  const first = parseMouseWheelEventsWithCarry("ab\x1b[<64;10", "");
  assert.deepEqual(first.events, []);
  assert.equal(first.passthrough, "ab");
  assert.equal(first.carry, "\x1b[<64;10");

  const second = parseMouseWheelEventsWithCarry(";5Mcd", first.carry);
  assert.deepEqual(second.events, [
    { kind: "wheel-up", col: 10, row: 5, modifiers: { shift: false, alt: false, ctrl: false } },
  ]);
  assert.equal(second.passthrough, "cd");
  assert.equal(second.carry, "");
});

test("chunkLooksLikeMouseEvent short-circuits on plain text", () => {
  assert.equal(chunkLooksLikeMouseEvent(""), false);
  assert.equal(chunkLooksLikeMouseEvent("abc"), false);
  assert.equal(chunkLooksLikeMouseEvent("\x1b[A"), false);
  assert.equal(chunkLooksLikeMouseEvent("\x1b[<64;0;0M"), true);
});

test("chunkLooksLikeMouseEvent detects mouse sequences after plain text", () => {
  assert.equal(chunkLooksLikeMouseEvent("hello \x1b[<64;10;5M"), true);
  assert.equal(chunkLooksLikeMouseEvent("hello \x1b[<64;10;5Mmore"), true);
});

test("chunkLooksLikeMouseEvent rejects non-mouse CSI prefix tails", () => {
  assert.equal(chunkLooksLikeMouseEvent("\x1b[<"), true);
  assert.equal(chunkLooksLikeMouseEvent("abc\x1b[<foo;bar"), false);
});
