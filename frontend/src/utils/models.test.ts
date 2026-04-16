import test from "node:test";
import assert from "node:assert/strict";

import {
  estimateContextWindow,
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

test("model-name heuristics recognize plan act and tool lanes", () => {
  assert.equal(isPlanLikeModel("switchhook-plan"), true);
  assert.equal(isActionLikeModel("oracle-main-act"), true);
  assert.equal(isToolLikeModel("oracle-fast"), true);
});

test("fast lane heuristics flag oracle-fast lanes", () => {
  assert.equal(isFastLaneModel("oracle-fast"), true);
  assert.equal(isFastLaneModel("oracle-main-fast"), true);
  assert.equal(isFastLaneModel({
    name: "worker",
    modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
    role: "planner",
  }), false);
  assert.equal(isFastLaneModel("nayru"), false);
});

test("modelPickerDescription appends fast-lane label for fast models", () => {
  assert.equal(modelOptInLabel("oracle-fast"), "fast lane");
  assert.equal(modelPickerDescription({
    name: "oracle-fast",
    modelId: "oracle-main-fast",
    role: "hybrid planner",
  }), "hybrid planner · fast lane");
  assert.equal(modelPickerDescription({
    name: "nayru",
    modelId: "nayru-model",
    role: "analysis",
  }), "analysis");
});
