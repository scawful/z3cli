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

test("dispatchCommand renders oracle tips text", async () => {
  const messages: string[] = [];

  await dispatchCommand("/oracle-tips", [], {
    config: null,
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/oracle-tips");
      assert.deepEqual(args, []);
      return {
        title: "Oracle Prompt Tips",
        text: "symptom + anchor + intent",
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

  assert.equal(messages.length, 1);
  assert.match(messages[0] ?? "", /Oracle Prompt Tips/);
  assert.match(messages[0] ?? "", /symptom \+ anchor \+ intent/);
});

test("dispatchCommand opens the model manager for /model-manager", async () => {
  let opened = 0;

  await dispatchCommand("/model-manager", [], {
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
    openHelp: () => {},
    openModelManager: () => {
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

test("dispatchCommand formats loaded model details", async () => {
  const messages: string[] = [];

  await dispatchCommand("/loaded", [], {
    config: null,
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string) => {
      assert.equal(cmd, "/loaded");
      return {
        loaded_models: [
          {
            identifier: "nayru",
            model_key: "gguf/zelda/nayru-9b-q8_0.gguf",
            display_name: "Nayru 9B",
            size_bytes: 9_527_501_152,
            status: "idle",
            parallel: 4,
            context_length: 262144,
            quantization: "Q8_0",
          },
        ],
        loaded_model_count: 1,
        loaded_model_memory_bytes: 9_527_501_152,
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

  assert.match(messages[0] ?? "", /Loaded Models/);
  assert.match(messages[0] ?? "", /nayru/);
  assert.match(messages[0] ?? "", /8\.87 GiB/);
});

test("dispatchCommand renders /models catalog from config", async () => {
  const messages: string[] = [];

  await dispatchCommand("/models", ["catalog"], {
    config: {
      version: "0.2.0-test",
      backend: "studio",
      activeModel: "oracle-pro",
      mode: "manual",
      workspace: "/tmp",
      romPath: "",
      toolsEnabled: true,
      servers: [],
      toolCount: 0,
      warnings: [],
      models: [],
      modelCatalog: [
        {
          name: "oracle-pro",
          modelId: "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
          role: "pro",
          loaded: true,
          toolsEnabled: true,
        },
      ],
      sessionPath: "",
    },
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => {
      throw new Error("catalog should render from config");
    },
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.match(messages[0] ?? "", /Model Catalog/);
  assert.match(messages[0] ?? "", /oracle-pro/);
});

test("dispatchCommand fetches /models routes from backend", async () => {
  const messages: string[] = [];

  await dispatchCommand("/models", ["routes"], {
    config: {
      version: "0.2.0-test",
      backend: "studio",
      activeModel: "oracle-pro",
      mode: "manual",
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
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/models");
      assert.deepEqual(args, ["routes"]);
      return {
        active: { backend: "studio", model: "oracle-pro" },
        entries: [
          {
            name: "oracle-pro-5090",
            backend: "studio",
            model: "oracle-pro",
            description: "Windows tunnel",
            aliases: ["home", "pro"],
          },
        ],
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

  assert.match(messages[0] ?? "", /Routes/);
  assert.match(messages[0] ?? "", /oracle-pro-5090/);
  assert.match(messages[0] ?? "", /aliases: `home`, `pro`/);
});

test("dispatchCommand shows immediate and final /use feedback", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const messages: string[] = [];

  await dispatchCommand("/use", ["home-ssh"], {
    config: {
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
      assert.equal(cmd, "/use");
      assert.deepEqual(args, ["home-ssh"]);
      return {
        backend: "llamacpp",
        model: "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
        resolved: "oracle-pro-home-ssh",
        llamacpp_node: "oracle-pro-home-ssh",
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

  assert.match(messages[0] ?? "", /Switching route to \*\*home-ssh\*\*/);
  assert.match(messages[1] ?? "", /Using \*\*oracle-pro-home-ssh\*\* via \*\*llamacpp\*\*/);
  assert.deepEqual(updates, [{
    backend: "llamacpp",
    activeModel: "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
  }]);
});

test("dispatchCommand renders /use route list payload", async () => {
  const messages: string[] = [];

  await dispatchCommand("/use", [], {
    config: {
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
      models: [],
      sessionPath: "",
    },
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/use");
      assert.deepEqual(args, []);
      return {
        active: { backend: "studio", model: "oracle" },
        entries: [
          { name: "oracle-pro-5090", backend: "studio", model: "oracle-pro", aliases: ["home"] },
        ],
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

  assert.match(messages[0] ?? "", /Routes/);
  assert.match(messages[0] ?? "", /oracle-pro-5090/);
});

test("dispatchCommand handles canonical /route selection", async () => {
  const updates: Array<Record<string, unknown>> = [];
  const messages: string[] = [];

  await dispatchCommand("/route", ["oracle-pro-5090"], {
    config: {
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
      assert.equal(cmd, "/route");
      assert.deepEqual(args, ["oracle-pro-5090"]);
      return {
        backend: "studio",
        model: "oracle-pro",
        route: "oracle-pro-5090",
        resolved: "oracle-pro-home",
        studio_node: "oracle-pro-home",
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

  assert.match(messages[0] ?? "", /Switching route to \*\*oracle-pro-5090\*\*/);
  assert.match(messages[1] ?? "", /Route set to \*\*oracle-pro-5090\*\* via \*\*studio\*\*/);
  assert.deepEqual(updates, [{
    backend: "studio",
    activeModel: "oracle-pro",
  }]);
});

test("dispatchCommand formats smoke failures explicitly", async () => {
  const messages: string[] = [];

  await dispatchCommand("/smoke", ["home-ssh"], {
    config: null,
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/smoke");
      assert.deepEqual(args, ["home-ssh"]);
      return {
        ok: false,
        matched: false,
        backend: "llamacpp",
        node: "oracle-pro-home-ssh",
        model: "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
        error: "ssh failed",
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

  assert.match(messages[0] ?? "", /Probing \*\*home-ssh\*\*/);
  assert.match(messages[1] ?? "", /Smoke Failed/);
  assert.match(messages[1] ?? "", /ssh failed/);
});

test("dispatchCommand reports unload results", async () => {
  const messages: string[] = [];

  await dispatchCommand("/unload", ["nayru"], {
    config: {
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
      models: [],
      sessionPath: "",
    },
    settings: {} as any,
    addSystemMessage: (content: string) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async (cmd: string, args?: string[]) => {
      assert.equal(cmd, "/unload");
      assert.deepEqual(args, ["nayru"]);
      return { target: "nayru", unloaded: ["nayru"], all: false };
    },
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.match(messages[0] ?? "", /Unloaded \*\*nayru\*\*/);
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
  assert.match(messages[0] ?? "", /Usage: `\/settings theme hyrule\|subrosia\|labrynna\|twilight`/);
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

test("dispatchCommand rejects removed transcript filter settings", async () => {
  const messages: string[] = [];

  await dispatchCommand("/settings", ["transcriptShowTools", "off"], {
    config: null,
    settings: {
      theme: "gold",
      uiMode: "chat",
    } as any,
    addSystemMessage: (content) => {
      messages.push(content);
    },
    replaceMessages: () => {},
    replaceSubagents: () => {},
    updateConfig: () => {},
    sendCommand: async () => null,
    sendMessage: async () => {},
    setSetting: () => {},
    resetSettings: () => {},
    openSettings: () => {},
    openHelp: () => {},
    openSessionPicker: () => {},
    exit: () => {},
  });

  assert.match(messages[0] ?? "", /Unknown setting: `transcriptShowTools`/);
});
