import test from "node:test";
import assert from "node:assert/strict";

import { dispatchCommand, normalizeSubagents } from "./index.js";

test("normalizeSubagents keeps valid restored entries", () => {
  const entries = normalizeSubagents([
    {
      id: "sub-1-worker",
      name: "worker",
      model: "worker",
      provider: "studio",
      depth: 2,
      parentId: "sub-0-planner",
      status: "done",
      text: "Patched resume flow",
      thinking: "",
      toolCallCount: 1,
      startedAt: 100,
      finishedAt: 250,
      promptTokens: 12,
      completionTokens: 6,
    },
  ]);

  assert.equal(entries.length, 1);
  assert.equal(entries[0]?.parentId, "sub-0-planner");
  assert.equal(entries[0]?.status, "done");
  assert.equal(entries[0]?.promptTokens, 12);
});

test("normalizeSubagents drops malformed restored entries", () => {
  const entries = normalizeSubagents([
    {
      id: "sub-1-worker",
      name: "worker",
      provider: "studio",
      depth: "bad",
    },
  ]);

  assert.deepEqual(entries, []);
});

test("dispatchCommand forwards /orchestrator and updates frontend config", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const messages: string[] = [];

  await dispatchCommand("/orchestrator", ["claude-sonnet"], {
    config: {
      version: "0.2.0-test",
      backend: "studio",
      activeModel: "oracle",
      mode: "orchestrator",
      workspace: "/tmp",
      romPath: "",
      toolsEnabled: true,
      servers: [],
      toolCount: 0,
      warnings: [],
      models: [],
      sessionPath: "",
    },
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: (patch) => {
      updates.push(patch as Record<string, unknown>);
    },
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/orchestrator");
      assert.deepEqual(args, ["claude-sonnet"]);
      return {
        orchestrator: "claude-sonnet",
        resolved: "claude-sonnet",
        auto_selected: false,
      };
    },
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(updates, [{ orchestratorModel: "claude-sonnet" }]);
  assert.equal(messages.length, 1);
  assert.match(messages[0] ?? "", /Orchestrator planner: \*\*claude-sonnet\*\*/);
});
