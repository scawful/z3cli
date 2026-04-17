import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { Backend } from "./backend.js";

test("Backend rejects pending requests when child exits", async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-backend-test-"));
  const scriptPath = path.join(tmp, "fake-python.sh");
  fs.writeFileSync(
    scriptPath,
    "#!/bin/sh\nsleep 0.2\nexit 1\n",
    { encoding: "utf8", mode: 0o755 },
  );

  const backend = new Backend(scriptPath);
  backend.start();
  try {
    await assert.rejects(
      backend.request("command", { cmd: "/status", args: [] }, 4_000),
      /Backend exited with code 1/,
    );
  } finally {
    backend.stop();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
