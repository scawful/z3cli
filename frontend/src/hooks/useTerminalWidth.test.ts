import test from "node:test";
import assert from "node:assert/strict";

import React from "react";
import { Text } from "ink";
import { render } from "ink-testing-library";

import { useTerminalWidth } from "./useTerminalWidth.js";
import { shouldShowContextPanel } from "../utils/transcript.js";

function WidthProbe(): React.ReactElement {
  const width = useTerminalWidth();
  return React.createElement(
    Text,
    null,
    shouldShowContextPanel(width, false) ? `wide:${width}` : `narrow:${width}`,
  );
}

function setColumns(columns: number): () => void {
  const previous = process.stdout.columns;
  Object.defineProperty(process.stdout, "columns", {
    value: columns,
    configurable: true,
    writable: true,
  });
  return () => {
    Object.defineProperty(process.stdout, "columns", {
      value: previous,
      configurable: true,
      writable: true,
    });
  };
}

async function waitFor(assertion: () => void, timeoutMs = 2000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      assertion();
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

test("useTerminalWidth reacts to stdout resize events", async () => {
  const restoreColumns = setColumns(100);
  const app = render(React.createElement(WidthProbe));

  try {
    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("narrow:100"));
    });

    Object.defineProperty(process.stdout, "columns", {
      value: 160,
      configurable: true,
      writable: true,
    });
    process.stdout.emit("resize");

    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("wide:160"));
    });
  } finally {
    app.unmount();
    restoreColumns();
  }
});
