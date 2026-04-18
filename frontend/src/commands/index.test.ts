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

test("dispatchCommand opens the help panel for /help", async () => {
  let opened = 0;

  await dispatchCommand("/help", [], {
    config: null,
    settings: {} as any,
    addSystemMessage: () => {},
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {
      opened += 1;
    },
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.equal(opened, 1);
});

test("dispatchCommand keeps local tool toggle state in sync", async () => {
  const messages: string[] = [];
  const updates: Array<Record<string, unknown>> = [];

  await dispatchCommand("/tools", ["off"], {
    config: null,
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
      assert.equal(cmd, "/tools");
      assert.deepEqual(args, ["off"]);
      return { ok: true };
    },
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(updates, [{ toolsEnabled: false }]);
  assert.match(messages[0] ?? "", /Tools disabled\./);
});

test("dispatchCommand keeps shell state in sync after /shell-reset", async () => {
  const messages: string[] = [];
  const updates: Array<Record<string, unknown>> = [];

  await dispatchCommand("/shell-reset", [], {
    config: {
      workspace: "/tmp/project",
    } as any,
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: (patch) => {
      updates.push(patch as Record<string, unknown>);
    },
    sendCommand: async (cmd: string) => {
      assert.equal(cmd, "/shell-reset");
      return { ok: true };
    },
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(updates, [{ shellActive: false, shellCwd: "/tmp/project" }]);
  assert.match(messages[0] ?? "", /Persistent shell reset\./);
});

test("dispatchCommand restores assistant thinking traces on /resume", async () => {
  let restoredMessages: any[] = [];

  await dispatchCommand("/resume", ["saved"], {
    config: null,
    settings: {} as any,
    addSystemMessage: () => {},
    replaceMessages: (messages) => {
      restoredMessages = messages;
    },
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/resume");
      assert.deepEqual(args, ["saved"]);
      return {
        resumed: "saved",
        messages_restored: 2,
        messages: [
          {
            id: "msg-1",
            role: "assistant",
            content: "Patched the room script.",
            thinking: "I should inspect the room header first.",
            timestamp: 123,
          },
        ],
        subagents: [],
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

  assert.equal(restoredMessages.length, 1);
  assert.equal(restoredMessages[0]?.thinking, "I should inspect the room header first.");
});

test("dispatchCommand restores construct refs on /resume", async () => {
  let restoredMessages: any[] = [];

  await dispatchCommand("/resume", ["saved"], {
    config: null,
    settings: {} as any,
    addSystemMessage: () => {},
    replaceMessages: (messages) => {
      restoredMessages = messages;
    },
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => ({
      resumed: "saved",
      messages_restored: 1,
      messages: [
        {
          id: "msg-1",
          role: "user",
          content: "inspect the room",
          timestamp: 123,
          constructRefs: [
            { kind: "room", query: "0x45", token: "#room:0x45", id: "0x45", label: "Glacia Estate (Jail Cells)" },
          ],
        },
      ],
      subagents: [],
    }),
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(restoredMessages[0]?.constructRefs, [
    { kind: "room", query: "0x45", token: "#room:0x45", id: "0x45", label: "Glacia Estate (Jail Cells)" },
  ]);
});

test("dispatchCommand rejects boolean-style values for enum settings", async () => {
  const messages: string[] = [];
  const setCalls: Array<[string, unknown]> = [];

  await dispatchCommand("/settings", ["theme", "off"], {
    config: null,
    settings: {
      theme: "gold",
      uiMode: "chat",
    } as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: (key, value) => {
      setCalls.push([key, value]);
    },
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(setCalls, []);
  assert.match(messages[0] ?? "", /Usage: `\/settings theme gold\|green\|red\|blue`/);
});

test("dispatchCommand applies enum settings with explicit values", async () => {
  const setCalls: Array<[string, unknown]> = [];

  await dispatchCommand("/settings", ["uiMode", "admin"], {
    config: null,
    settings: {
      theme: "gold",
      uiMode: "chat",
    } as any,
    addSystemMessage: () => {},
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: (key, value) => {
      setCalls.push([key, value]);
    },
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(setCalls, [["uiMode", "admin"]]);
});

test("dispatchCommand applies reasoning visibility enum values", async () => {
  const setCalls: Array<[string, unknown]> = [];

  await dispatchCommand("/settings", ["showThinking", "streamed-only"], {
    config: null,
    settings: {
      theme: "gold",
      uiMode: "chat",
      showThinking: "transcript",
    } as any,
    addSystemMessage: () => {},
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: (key, value) => {
      setCalls.push([key, value]);
    },
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(setCalls, [["showThinking", "streamed-only"]]);
});

test("dispatchCommand applies reasoning detail enum values", async () => {
  const setCalls: Array<[string, unknown]> = [];

  await dispatchCommand("/settings", ["thinkingDetail", "full"], {
    config: null,
    settings: {
      theme: "gold",
      uiMode: "chat",
      showThinking: "transcript",
      thinkingDetail: "preview",
    } as any,
    addSystemMessage: () => {},
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: (key, value) => {
      setCalls.push([key, value]);
    },
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.deepEqual(setCalls, [["thinkingDetail", "full"]]);
});
