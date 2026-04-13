#!/usr/bin/env node
/**
 * z3cli-ui — Terminal UI frontend for z3cli.
 *
 * Spawns the Python z3cli backend in --serve mode and renders
 * an Ink (React) based terminal interface.
 */

import React from "react";
import { render } from "ink";
import { App } from "./components/App.js";
import { resolve } from "node:path";
import { existsSync, readFileSync } from "node:fs";

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

// Forward CLI args to the Python backend
const backendArgs = process.argv.slice(2);
const batchCommands = process.stdin.isTTY
  ? []
  : readFileSync(0, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

// Render the app
const { waitUntilExit } = render(
  <App pythonPath={pythonPath} backendArgs={backendArgs} batchCommands={batchCommands} />,
);

waitUntilExit().then(() => {
  process.exit(0);
});
