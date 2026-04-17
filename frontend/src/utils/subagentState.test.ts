import test from "node:test";
import assert from "node:assert/strict";

import {
  applySubagentEvent,
  buildSubagentForest,
  pruneFinishedSubagents,
  type SubagentEntry,
} from "./subagentState.js";

function startEvent(id: string, name: string = "nayru", model: string = "nayru") {
  return {
    kind: "start" as const,
    id,
    name,
    model,
    provider: "studio",
    depth: 0,
  };
}

test("start adds a new running entry", () => {
  const state = applySubagentEvent([], startEvent("s1"), 1000);
  assert.equal(state.length, 1);
  const entry = state[0]!;
  assert.equal(entry.id, "s1");
  assert.equal(entry.status, "running");
  assert.equal(entry.text, "");
  assert.equal(entry.startedAt, 1000);
});

test("start with existing id replaces the entry", () => {
  let state = applySubagentEvent([], startEvent("s1"), 1000);
  state = applySubagentEvent(state, { kind: "text", id: "s1", delta: "hello" });
  // Duplicate start with same id should reset the entry
  state = applySubagentEvent(state, startEvent("s1"), 2000);
  assert.equal(state.length, 1);
  assert.equal(state[0]!.text, "");
  assert.equal(state[0]!.startedAt, 2000);
});

test("text deltas accumulate", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, { kind: "text", id: "s1", delta: "Hello " });
  state = applySubagentEvent(state, { kind: "text", id: "s1", delta: "world" });
  assert.equal(state[0]!.text, "Hello world");
});

test("thinking deltas accumulate on a separate field", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, { kind: "thinking", id: "s1", delta: "let me think…" });
  assert.equal(state[0]!.thinking, "let me think…");
  assert.equal(state[0]!.text, "");
});

test("tool_call increments count and sets active tool", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, {
    kind: "tool_call", id: "s1", name: "echo", server: "mock",
  });
  assert.equal(state[0]!.toolCallCount, 1);
  assert.deepEqual(state[0]!.activeTool, { name: "echo", server: "mock" });
});

test("tool_result clears active tool but preserves count", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, {
    kind: "tool_call", id: "s1", name: "echo", server: "mock",
  });
  state = applySubagentEvent(state, { kind: "tool_result", id: "s1" });
  assert.equal(state[0]!.toolCallCount, 1);
  assert.equal(state[0]!.activeTool, undefined);
});

test("done marks entry complete and records tokens", () => {
  let state = applySubagentEvent([], startEvent("s1"), 1000);
  state = applySubagentEvent(state, { kind: "text", id: "s1", delta: "partial" });
  state = applySubagentEvent(
    state,
    {
      kind: "done",
      id: "s1",
      name: "nayru",
      model: "nayru",
      text: "",  // empty summary — should keep streamed text
      promptTokens: 100,
      completionTokens: 50,
      toolCalls: 0,
    },
    5000,
  );
  assert.equal(state[0]!.status, "done");
  assert.equal(state[0]!.text, "partial");
  assert.equal(state[0]!.promptTokens, 100);
  assert.equal(state[0]!.completionTokens, 50);
  assert.equal(state[0]!.finishedAt, 5000);
});

test("done with error text marks status as error", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, {
    kind: "done", id: "s1", name: "x", model: "x", text: "",
    promptTokens: 0, completionTokens: 0, toolCalls: 0,
    error: "bridge missing",
  });
  assert.equal(state[0]!.status, "error");
  assert.equal(state[0]!.error, "bridge missing");
});

test("done with cancelled flag marks status as cancelled", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(state, {
    kind: "done", id: "s1", name: "x", model: "x", text: "",
    promptTokens: 0, completionTokens: 0, toolCalls: 0,
    cancelled: true,
  });
  assert.equal(state[0]!.status, "cancelled");
});

test("error event sets status and message", () => {
  let state = applySubagentEvent([], startEvent("s1"));
  state = applySubagentEvent(
    state,
    { kind: "error", id: "s1", message: "network failure" },
    9999,
  );
  assert.equal(state[0]!.status, "error");
  assert.equal(state[0]!.error, "network failure");
  assert.equal(state[0]!.finishedAt, 9999);
});

test("unknown id on text event is silently ignored", () => {
  const state = applySubagentEvent(
    [{
      id: "s1", name: "x", model: "x", provider: "studio",
      depth: 0, status: "running", text: "", thinking: "", toolCallCount: 0, startedAt: 0,
    } satisfies SubagentEntry],
    { kind: "text", id: "nonexistent", delta: "hi" },
  );
  assert.equal(state[0]!.text, "");
});

test("pruneFinishedSubagents drops completed entries by default", () => {
  const entries: SubagentEntry[] = [
    { id: "a", name: "a", model: "a", provider: "studio", status: "running",
      depth: 0, text: "", thinking: "", toolCallCount: 0, startedAt: 0 },
    { id: "b", name: "b", model: "b", provider: "studio", status: "done",
      depth: 0, text: "", thinking: "", toolCallCount: 0, startedAt: 0, finishedAt: 100 },
    { id: "c", name: "c", model: "c", provider: "studio", status: "error",
      depth: 0, text: "", thinking: "", toolCallCount: 0, startedAt: 0, finishedAt: 100 },
  ];
  const pruned = pruneFinishedSubagents(entries);
  assert.equal(pruned.length, 1);
  assert.equal(pruned[0]!.id, "a");
});

test("pruneFinishedSubagents respects maxAgeMs window", () => {
  const entries: SubagentEntry[] = [
    { id: "old", name: "a", model: "a", provider: "studio", status: "done",
      depth: 0, text: "", thinking: "", toolCallCount: 0, startedAt: 0, finishedAt: 1000 },
    { id: "new", name: "b", model: "b", provider: "studio", status: "done",
      depth: 0, text: "", thinking: "", toolCallCount: 0, startedAt: 0, finishedAt: 5000 },
  ];
  const pruned = pruneFinishedSubagents(entries, 6000, 3000);
  // old finished at 1000 (5s ago) — outside 3s window, pruned
  // new finished at 5000 (1s ago) — kept
  assert.equal(pruned.length, 1);
  assert.equal(pruned[0]!.id, "new");
});

test("buildSubagentForest nests children under their parent id", () => {
  const entries: SubagentEntry[] = [
    {
      id: "root",
      name: "planner",
      model: "planner",
      provider: "studio",
      depth: 1,
      status: "running",
      text: "",
      thinking: "",
      toolCallCount: 0,
      startedAt: 0,
    },
    {
      id: "child",
      name: "worker",
      model: "worker",
      provider: "studio",
      depth: 2,
      parentId: "root",
      status: "running",
      text: "",
      thinking: "",
      toolCallCount: 0,
      startedAt: 1,
    },
    {
      id: "sibling-root",
      name: "other",
      model: "other",
      provider: "studio",
      depth: 0,
      status: "done",
      text: "",
      thinking: "",
      toolCallCount: 0,
      startedAt: 2,
    },
  ];

  const forest = buildSubagentForest(entries);
  assert.equal(forest.length, 2);
  assert.equal(forest[0]!.entry.id, "root");
  assert.equal(forest[0]!.children.length, 1);
  assert.equal(forest[0]!.children[0]!.entry.id, "child");
  assert.equal(forest[1]!.entry.id, "sibling-root");
});

test("buildSubagentForest ignores parent cycles instead of recursing forever", () => {
  const entries: SubagentEntry[] = [
    {
      id: "a",
      name: "planner",
      model: "planner",
      provider: "studio",
      depth: 1,
      parentId: "b",
      status: "running",
      text: "",
      thinking: "",
      toolCallCount: 0,
      startedAt: 0,
    },
    {
      id: "b",
      name: "worker",
      model: "worker",
      provider: "studio",
      depth: 2,
      parentId: "a",
      status: "running",
      text: "",
      thinking: "",
      toolCallCount: 0,
      startedAt: 1,
    },
  ];

  const forest = buildSubagentForest(entries);
  assert.equal(forest.length, 1);
  assert.equal(forest[0]!.entry.id, "a");
  assert.equal(forest[0]!.children.length, 1);
  assert.equal(forest[0]!.children[0]!.entry.id, "b");
  assert.equal(forest[0]!.children[0]!.children.length, 0);
});
