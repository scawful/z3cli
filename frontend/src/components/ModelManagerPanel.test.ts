import test from "node:test";
import assert from "node:assert/strict";

import { buildModelManagerEntries, buildModelManagerTabs } from "./ModelManagerPanel.js";

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

  const nayru = entries.find((entry) => entry.name === "nayru");
  const residentExtra = entries.find((entry) => entry.name === "resident-extra");
  const oraclePro = entries.find((entry) => entry.name === "oracle-pro");

  assert.equal(nayru?.active, true);
  assert.equal(nayru?.canUnload, true);
  assert.equal(residentExtra?.canActivate, false);
  assert.equal(oraclePro?.canLoad, true);
});

test("buildModelManagerTabs groups oracle and qwen families separately", () => {
  const tabs = buildModelManagerTabs({
    version: "0.2.0-test",
    backend: "studio",
    activeModel: "oracle",
    mode: "manual",
    workspace: "/tmp",
    romPath: "",
    toolsEnabled: true,
    servers: [],
    toolCount: 0,
    warnings: [],
    models: [
      {
        name: "oracle",
        modelId: "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf",
        role: "planner",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
      {
        name: "qwen3-local-8b",
        modelId: "qwen/qwen3-8b",
        role: "general qwen",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
    ],
    modelCatalog: [
      {
        name: "oracle",
        modelId: "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf",
        role: "planner",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
      {
        name: "oracle-pro",
        modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
        role: "heavy oracle",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
      {
        name: "qwen3-local-8b",
        modelId: "qwen/qwen3-8b",
        role: "general qwen",
        loaded: false,
        toolsEnabled: true,
        provider: "studio",
      },
    ],
    sessionPath: "",
  } as any);

  assert.deepEqual(tabs.map((tab) => tab.label), ["Oracle", "Qwen"]);
  assert.deepEqual(tabs[0]?.entries.map((entry) => entry.name), ["oracle", "oracle-pro"]);
  assert.equal(tabs[0]?.entries[1]?.canActivate, false);
  assert.equal(tabs[0]?.entries[1]?.catalogTag, "manual");
  assert.deepEqual(tabs[1]?.entries.map((entry) => entry.name), ["qwen3-local-8b"]);
});
