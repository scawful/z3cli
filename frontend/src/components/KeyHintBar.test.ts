import test from "node:test";
import assert from "node:assert/strict";

import { KEYBOARD_LEGEND_ITEMS } from "./KeyHintBar.js";

test("KeyHintBar exposes the compact core shortcut list", () => {
  assert.deepEqual(
    KEYBOARD_LEGEND_ITEMS,
    [
      { key: "[Ctrl+P]", label: "Palette" },
      { key: "[Tab]", label: "Complete" },
      { key: "[Shift+Tab]", label: "Mode" },
    ],
  );
});

test("App.tsx re-exports the same list for backwards compatibility", async () => {
  const fromApp = await import("./App.js");
  assert.equal(fromApp.KEYBOARD_LEGEND_ITEMS, KEYBOARD_LEGEND_ITEMS);
});
