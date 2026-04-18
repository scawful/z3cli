import test from "node:test";
import assert from "node:assert/strict";

import { clampScrollOffset, scrollTargetBy, type ScrollClampTarget } from "./scrolling.js";

test("clampScrollOffset clamps below zero and above bottom", () => {
  assert.equal(clampScrollOffset(-1, 10), 0);
  assert.equal(clampScrollOffset(11, 10), 10);
  assert.equal(clampScrollOffset(5, 10), 5);
});

test("scrollTargetBy clamps down-scroll movement to bottom", () => {
  let offset = 8;
  const target: ScrollClampTarget = {
    getScrollOffset: () => offset,
    getBottomOffset: () => 10,
    scrollTo: (next) => {
      offset = next;
    },
  };

  scrollTargetBy(target, 5);
  assert.equal(offset, 10);
});

test("scrollTargetBy clamps up-scroll movement to top", () => {
  let offset = 2;
  const target: ScrollClampTarget = {
    getScrollOffset: () => offset,
    getBottomOffset: () => 10,
    scrollTo: (next) => {
      offset = next;
    },
  };

  scrollTargetBy(target, -5);
  assert.equal(offset, 0);
});
