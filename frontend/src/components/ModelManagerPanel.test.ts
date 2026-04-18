import test from "node:test";
import assert from "node:assert/strict";

import { buildModelManagerEntries } from "./ModelManagerPanel.js";

test("buildModelManagerEntries merges configured and resident-only loaded models", () => {
  const entries = buildModelManagerEntries({
    version: "0.2.0-test",
    backend: "studio",
    activeModel: "nayru",
    mode: "manual",
    workspace: "/tmp",
    romPath: "",
    toolsEnabled: true,
    servers: [],
    toolCount: 0,
    warnings: [],
    models: [
      {
        name: "nayru",
        modelId: "gguf/zelda/nayru-9b-q8_0.gguf",
        role: "analysis",
        loaded: true,
        toolsEnabled: true,
        provider: "studio",
        loadedIdentifier: "nayru",
        sizeBytes: 9_527_501_152,
        status: "idle",
        contextLength: 262144,
        quantization: "Q8_0",
      },
      {
        name: "oracle-pro",
        modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
        role: "planner",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
    ],
    loadedModels: [
      {
        identifier: "nayru",
        modelKey: "gguf/zelda/nayru-9b-q8_0.gguf",
        sizeBytes: 9_527_501_152,
      },
      {
        identifier: "resident-extra",
        modelKey: "gguf/zelda/extra.gguf",
        sizeBytes: 2_147_483_648,
      },
    ],
    loadedModelCount: 2,
    loadedModelMemoryBytes: 11_674_984_800,
    sessionPath: "",
  } as any);

  assert.equal(entries[0]?.name, "nayru");
  assert.equal(entries[0]?.active, true);
  assert.equal(entries[0]?.canUnload, true);
  assert.equal(entries[1]?.name, "resident-extra");
  assert.equal(entries[1]?.canActivate, false);
  assert.equal(entries[2]?.name, "oracle-pro");
  assert.equal(entries[2]?.canLoad, true);
});
