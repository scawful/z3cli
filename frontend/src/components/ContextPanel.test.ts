import test from "node:test";
import assert from "node:assert/strict";
import { buildLoadedModelLines, deriveContextPanelLimits } from "./ContextPanel.js";
import type { AppConfig } from "../ipc/protocol.js";

function makeConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    version: "0.2.0",
    backend: "studio",
    activeModel: "oracle",
    mode: "manual",
    workspace: "/tmp/ws",
    romPath: "",
    toolsEnabled: true,
    servers: [],
    toolCount: 0,
    warnings: [],
    models: [],
    sessionPath: "",
    ...overrides,
  };
}

test("deriveContextPanelLimits shrinks diagnostics and lists on shorter rails", () => {
  assert.deepEqual(deriveContextPanelLimits(36, 24), {
    compact: false,
    draftFilesLimit: 5,
    recentSessionsLimit: 4,
    loadedModelsLimit: 4,
  });

  assert.deepEqual(deriveContextPanelLimits(30, 16), {
    compact: true,
    draftFilesLimit: 3,
    recentSessionsLimit: 2,
    loadedModelsLimit: 2,
  });
});

test("buildLoadedModelLines summarizes concurrent loaded models", () => {
  const lines = buildLoadedModelLines(makeConfig({
    loadedModels: [
      {
        identifier: "nayru",
        modelKey: "gguf/zelda/nayru-9b-q8_0.gguf",
        sizeBytes: 9_527_501_152,
        status: "idle",
        parallel: 4,
        contextLength: 262144,
        quantization: "Q8_0",
        estimatedGpuBytes: 10_683_469_824,
        estimatedTotalBytes: 10_683_469_824,
      },
      {
        identifier: "oracle",
        modelKey: "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf",
        sizeBytes: 5_027_783_520,
        status: "busy",
        queued: 1,
        contextLength: 40960,
        quantization: "Q4_K_M",
      },
    ],
  }), 4);

  assert.deepEqual(lines, [
    "nayru · 8.87 GiB · idle · p4 · ctx 262k · Q8_0 · gpu/total 9.95 GiB",
    "oracle · 4.68 GiB · busy · q1 · ctx 41k · Q4_K_M",
  ]);
});
