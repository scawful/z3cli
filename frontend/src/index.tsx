#!/usr/bin/env node
/**
 * z3cli-ui — Terminal UI frontend for z3cli.
 *
 * Spawns the Python z3cli backend in --serve mode and renders
 * an Ink (React) based terminal interface.
 */

import React from "react";
import { render } from "ink";
import { App, type AppSummarySnapshot } from "./components/App.js";
import { resolve } from "node:path";
import { existsSync, readFileSync } from "node:fs";
import { CLEAR_SCREEN, renderExitBanner } from "./utils/exitBanner.js";
import { parseCliArgs } from "./utils/cliArgs.js";
import { createMouseFilteredStdin } from "./utils/mouseStdin.js";

// Resolve the Python backend path
const defaultPython = resolve(
  import.meta.dirname,
  "..",
  "..",
  "venv",
  "bin",
  "python",
);

const pythonPath = process.env.Z3CLI_PYTHON ?? (
  existsSync(defaultPython) ? defaultPython : "python3"
);

// Split frontend flags out of argv (e.g. --resume) so Python only sees args
// it understands.
const { backendArgs, startupCommands } = parseCliArgs(process.argv.slice(2));

const stdinCommands = process.stdin.isTTY
  ? []
  : readFileSync(0, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

// Startup commands (from --resume etc.) run before stdin-fed batch commands so
// the resumed session is the state the piped commands operate against.
const batchCommands = [...startupCommands, ...stdinCommands];

const startedAt = Date.now();
let latestSnapshot: AppSummarySnapshot | null = null;
const filteredStdin = process.stdin.isTTY ? createMouseFilteredStdin() : process.stdin;

// Render the app
const { waitUntilExit } = render(
  <App
    pythonPath={pythonPath}
    backendArgs={backendArgs}
    batchCommands={batchCommands}
    onSummaryUpdate={(snapshot) => { latestSnapshot = snapshot; }}
  />,
  {
    stdin: filteredStdin,
  },
);

waitUntilExit().then(() => {
  if (filteredStdin !== process.stdin) {
    filteredStdin.destroy();
  }
  if (latestSnapshot && process.stdout.isTTY) {
    const banner = renderExitBanner({
      ...latestSnapshot,
      durationMs: Date.now() - startedAt,
    });
    process.stdout.write(CLEAR_SCREEN + banner);
  }
  process.exit(0);
});
