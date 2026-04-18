import test from "node:test";
import assert from "node:assert/strict";
import { buildDiagnosticsLines, buildLoadedModelLines, deriveContextPanelLimits } from "./ContextPanel.js";
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
    diagnosticsLineLimit: 7,
    draftFilesLimit: 5,
    recentSessionsLimit: 4,
    loadedModelsLimit: 4,
  });

  assert.deepEqual(deriveContextPanelLimits(30, 16), {
    compact: true,
    diagnosticsLineLimit: 4,
    draftFilesLimit: 3,
    recentSessionsLimit: 2,
    loadedModelsLimit: 2,
  });
});

test("buildDiagnosticsLines keeps diagnostics compact and omits id spam", () => {
  const lines = buildDiagnosticsLines(
    makeConfig({
      requestCount: 9,
      requestSuccessCount: 7,
      requestErrorCount: 1,
      requestRejectCount: 1,
      requestCancelCount: 0,
      toolLatencyMs: 42,
      toolLatencySamples: 3,
      permissionWaitMs: 8,
      reviewWaitMs: 5,
      permissionTimeoutCount: 1,
      reviewTimeoutCount: 0,
      modelRetryCount: 2,
      modelRetryBackoffMs: 1200,
      modelErrorCount: 1,
      toolTimeoutCount: 0,
      modelBackpressureCount: 0,
      toolBackpressureCount: 1,
      inflightModelCalls: 1,
      queuedModelCalls: 0,
      inflightToolCalls: 0,
      queuedToolCalls: 1,
      maxInflightModelCalls: 1,
      maxInflightTools: 2,
      execQueueDepth: 4,
      requestSamples: 4,
      queuedMsP50: 1,
      modelMsP50: 120,
      toolMsP50: 7,
      totalMsP50: 130,
      queuedMsP95: 3,
      modelMsP95: 220,
      toolMsP95: 12,
      totalMsP95: 240,
      lastRequestStatus: "success",
      lastRequestQueuedMs: 1,
      lastRequestModelMs: 118,
      lastRequestToolMs: 6,
      lastRequestTotalMs: 125,
      lastRequestId: "req-123",
      lastSpanId: "span-123",
      lastToolCallId: "call-123",
    }),
    5,
    true,
  );

  assert.equal(lines.length, 5);
  assert.ok(lines.some((line) => line.includes("req 9")));
  assert.ok(lines.some((line) => line.includes("tool avg 42ms")));
  assert.ok(lines.some((line) => line.includes("budget m 1/1+0/4")));
  assert.ok(lines.every((line) => !line.includes("req-123")));
  assert.ok(lines.every((line) => !line.includes("span-123")));
  assert.ok(lines.every((line) => !line.includes("call-123")));
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
    "nayru · 8.87 GiB · idle · p4 · ctx 262k · Q8_0",
    "oracle · 4.68 GiB · busy · q1 · ctx 41k · Q4_K_M",
  ]);
});
