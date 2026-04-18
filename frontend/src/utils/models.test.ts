import test from "node:test";
import assert from "node:assert/strict";

import {
  describeLoadedModelRuntime,
  estimateContextWindow,
  formatContextLength,
  formatModelEstimate,
  formatModelMemory,
  isActionLikeModel,
  isFastLaneModel,
  isPlanLikeModel,
  isToolLikeModel,
  modelOptInLabel,
  modelPickerDescription,
} from "./models.js";

test("estimateContextWindow prefers explicit backend context budgets", () => {
  const value = estimateContextWindow("oracle-main-plan", [{
    name: "oracle-main-plan",
    modelId: "oracle-main-plan",
    role: "planner",
    loaded: true,
    toolsEnabled: true,
    provider: "studio",
    contextBudget: 65536,
  }]);

  assert.equal(value, 65536);
});

test("estimateContextWindow falls back to larger windows for plan and act models", () => {
  assert.equal(estimateContextWindow("qwen3-oracle-plan"), 32768);
  assert.equal(estimateContextWindow("qwen3-oracle-act"), 32768);
});

test("estimateContextWindow handles oracle and oracle-fast aliases", () => {
  assert.equal(estimateContextWindow("oracle"), 32768);
  assert.equal(estimateContextWindow("oracle-pro"), 32768);
  assert.equal(estimateContextWindow("oracle-fast"), 16384);
  assert.equal(estimateContextWindow("oracle-main-fast"), 16384);
});

test("estimateContextWindow treats cloud models as large-context by default", () => {
  const value = estimateContextWindow("claude-sonnet", [{
    name: "claude-sonnet",
    modelId: "claude-sonnet-4",
    role: "planner",
    loaded: true,
    toolsEnabled: true,
    provider: "anthropic",
  }]);

  assert.equal(value, 200000);
});

test("model-name heuristics recognize plan act and tool models", () => {
  assert.equal(isPlanLikeModel("switchhook-plan"), true);
  assert.equal(isActionLikeModel("oracle-main-act"), true);
  assert.equal(isToolLikeModel("oracle-fast"), true);
});

test("fast model heuristics flag oracle-fast models", () => {
  assert.equal(isFastLaneModel("oracle-fast"), true);
  assert.equal(isFastLaneModel("oracle-main-fast"), true);
  assert.equal(isFastLaneModel({
    name: "worker",
    modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
    role: "planner",
  }), false);
  assert.equal(isFastLaneModel("nayru"), false);
});

test("modelPickerDescription appends fast and heavy labels", () => {
  assert.equal(modelOptInLabel("oracle-fast"), "fast");
  assert.equal(modelOptInLabel("oracle-pro"), "manual heavy");
  assert.equal(modelPickerDescription({
    name: "oracle-fast",
    modelId: "oracle-main-fast",
    role: "hybrid planner",
    description: "8-9B fast model · live alias",
  }), "8-9B fast model · live alias · fast");
  assert.equal(modelPickerDescription({
    name: "oracle-pro",
    modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
    role: "hybrid planner",
    description: "27B switchhook Oracle · q4km",
  }), "27B switchhook Oracle · q4km · manual heavy");
  assert.equal(modelPickerDescription({
    name: "nayru",
    modelId: "nayru-model",
    role: "analysis",
    description: "9B Qwen3.5 explainer · q8_0",
  }), "9B Qwen3.5 explainer · q8_0");
});

test("formatModelMemory and context helpers stay compact", () => {
  assert.equal(formatModelMemory(9_527_501_152), "8.87 GiB");
  assert.equal(formatContextLength(262144), "ctx 262k");
});

test("describeLoadedModelRuntime includes load status and memory hints", () => {
  assert.equal(describeLoadedModelRuntime({
    sizeBytes: 9_527_501_152,
    status: "idle",
    parallel: 4,
    queued: 0,
    contextLength: 262144,
    quantization: "Q8_0",
  }), "8.87 GiB · idle · p4 · ctx 262k · Q8_0");
});

test("formatModelEstimate handles equal and split gpu/total estimates", () => {
  assert.equal(formatModelEstimate(10_683_469_824, 10_683_469_824), "gpu/total 9.95 GiB");
  assert.equal(formatModelEstimate(5_368_709_120, 10_683_469_824), "gpu 5.00 GiB · total 9.95 GiB");
});
