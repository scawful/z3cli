import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import React from "react";
import { render } from "ink-testing-library";

import { PromptInput } from "./PromptInput.js";
import type { AttachmentMeta, ConstructRef } from "../ipc/protocol.js";
import { SettingsContext } from "../contexts/SettingsContext.js";
import { DEFAULT_SETTINGS } from "../hooks/useSettings.js";
import { getThemeColors } from "../theme/index.js";

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeFrame(frame: string | undefined): string {
  return (frame ?? "").replace(/\s+/g, " ").trim();
}

function setTTY(enabled: boolean): () => void {
  const hadOwn = Object.prototype.hasOwnProperty.call(process.stdin, "isTTY");
  const previous = process.stdin.isTTY;
  Object.defineProperty(process.stdin, "isTTY", {
    value: enabled,
    configurable: true,
    writable: true,
  });
  return () => {
    if (hadOwn) {
      Object.defineProperty(process.stdin, "isTTY", {
        value: previous,
        configurable: true,
        writable: true,
      });
    } else {
      delete (process.stdin as { isTTY?: boolean }).isTTY;
    }
  };
}

async function waitFor(assertion: () => void, timeoutMs = 2000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      assertion();
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function typeText(
  stdin: { write: (chunk: string) => void },
  text: string,
  pauseMs = 40,
): Promise<void> {
  for (const char of text) {
    stdin.write(char);
    await sleep(pauseMs);
  }
}

async function openPalette(app: { stdin: { write: (chunk: string) => void }; lastFrame: () => string | undefined }): Promise<void> {
  let lastFrame = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    app.stdin.write("\x10");
    try {
      await waitFor(() => {
        lastFrame = normalizeFrame(app.lastFrame());
        assert.ok(lastFrame.includes("Command palette"));
      }, 750);
      return;
    } catch {
      await sleep(100);
    }
  }
  throw new Error(`Command palette did not open. Last frame: ${lastFrame}`);
}

const MODEL_FIXTURE = [
  {
    name: "nayru",
    modelId: "nayru-model",
    role: "analysis",
    loaded: true,
    toolsEnabled: true,
  },
];

function renderPromptInput(props: React.ComponentProps<typeof PromptInput>) {
  return render(
    React.createElement(
      SettingsContext.Provider,
      {
        value: {
          settings: DEFAULT_SETTINGS,
          colors: getThemeColors(DEFAULT_SETTINGS.theme),
          toggleSetting: () => {},
          setSetting: () => {},
          resetSettings: () => {},
          cycleMode: () => {},
          cycleTheme: () => {},
          cycleThinkingMode: () => {},
          cycleThinkingDetail: () => {},
        },
      },
      React.createElement(PromptInput, props),
    ),
  );
}

test("PromptInput model picker marks fast model", async () => {
  const restoreTTY = setTTY(true);
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: [
      ...MODEL_FIXTURE,
      {
        name: "oracle-fast",
        modelId: "gguf/zelda/switchhook-27b-v1-q4km.gguf",
        role: "hybrid planner",
        loaded: false,
        toolsEnabled: true,
      },
    ],
    workspace: process.cwd(),
    disabled: false,
    onSubmit: () => {},
  });

  try {
    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("❯"));
    });
    await sleep(200);

    await typeText(app.stdin, "/model");
    app.stdin.write("\r");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("Select model"));
      assert.ok(frame.includes("oracle-fast"));
      assert.ok(frame.includes("fast"));
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
  }
});

test("PromptInput inserts @file references from the interactive picker", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "src"), { recursive: true });
  fs.writeFileSync(path.join(workspace, "src", "room.asm"), "lda #$01\n", "utf8");
  fs.writeFileSync(path.join(workspace, "src", "main.asm"), "sta $7E0010\n", "utf8");

  let draftFiles: AttachmentMeta[] = [];
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: () => {},
    onDraftFilesChange: (files: AttachmentMeta[]) => {
      draftFiles = files;
    },
  });

  try {
    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("❯"));
    });
    await sleep(250);

    await typeText(app.stdin, "@room");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("File reference"));
      assert.ok(frame.includes("src/room.asm"));
    }, 4000);

    app.stdin.write("\r");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("@src/room.asm"));
      assert.deepEqual(
        draftFiles.map((file) => file.path),
        ["src/room.asm"],
      );
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput inserts #refs from the interactive picker", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "Docs", "Dev", "Planning"), { recursive: true });
  fs.writeFileSync(
    path.join(workspace, "Docs", "Dev", "Planning", "oracle_resource_labels.json"),
    JSON.stringify({ room: { "0x45": "Glacia Estate (Jail Cells)" } }),
    "utf8",
  );

  let draftRefs: ConstructRef[] = [];
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: () => {},
    onDraftConstructRefsChange: (refs: ConstructRef[]) => {
      draftRefs = refs;
    },
  });

  try {
    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("❯"));
    });
    await sleep(250);

    await typeText(app.stdin, "#room:gla");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("Game reference"));
      assert.ok(frame.includes("#room:0x45"));
    }, 4000);

    app.stdin.write("\r");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("#room:0x45"));
      assert.deepEqual(draftRefs, [{
        kind: "room",
        query: "0x45",
        token: "#room:0x45",
        id: "0x45",
        label: "Glacia Estate (Jail Cells)",
      }]);
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput shows construct disambiguation metadata before attach", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "Docs", "Dev", "Planning"), { recursive: true });
  fs.writeFileSync(
    path.join(workspace, "Docs", "Dev", "Planning", "oracle_resource_labels.json"),
    JSON.stringify({
      room: {
        "0x45": "Glacia Estate (Jail Cells)",
        "0x46": "Glade Ruins",
      },
    }),
    "utf8",
  );

  let draftRefs: ConstructRef[] = [];
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: () => {},
    onDraftConstructRefsChange: (refs: ConstructRef[]) => {
      draftRefs = refs;
    },
  });

  try {
    await sleep(250);
    await typeText(app.stdin, "#room:gla");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("Disambiguate reference"));
      assert.ok(frame.includes("2 close matches - choose one or keep typing"));
      assert.ok(frame.includes("resource labels"));
    }, 4000);

    app.stdin.write("\r");

    await waitFor(() => {
      assert.deepEqual(draftRefs, [{
        kind: "room",
        query: "0x46",
        token: "#room:0x46",
        id: "0x46",
        label: "Glade Ruins",
      }]);
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput removes the last attached file with Backspace on an empty prompt", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "src"), { recursive: true });
  fs.writeFileSync(path.join(workspace, "src", "room.asm"), "lda #$01\n", "utf8");

  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: () => {},
  });

  try {
    await waitFor(() => {
      assert.ok(app.lastFrame()?.includes("❯"));
    });
    await sleep(250);
    await typeText(app.stdin, "@room");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("File reference"));
    }, 4000);
    app.stdin.write("\r");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("@src/room.asm"));
    }, 4000);

    app.stdin.write("\x7f");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(!frame.includes("@src/room.asm"));
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput submits structured attachments without rewriting the prompt text", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "src"), { recursive: true });
  fs.writeFileSync(path.join(workspace, "src", "room.asm"), "lda #$01\n", "utf8");

  let submittedText = "";
  let submittedAttachments: AttachmentMeta[] = [];
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: (text: string, attachments?: AttachmentMeta[]) => {
      submittedText = text;
      submittedAttachments = attachments ?? [];
    },
  });

  try {
    await sleep(200);
    await typeText(app.stdin, "@room");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("File reference"));
    }, 4000);
    app.stdin.write("\r");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("@src/room.asm"));
    }, 4000);

    await typeText(app.stdin, "inspect this file");
    app.stdin.write("\r");

    await waitFor(() => {
      assert.equal(submittedText, "inspect this file");
      assert.deepEqual(submittedAttachments, [{ path: "src/room.asm", lines: 2, chars: 9 }]);
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput submits structured construct refs without rewriting the prompt text", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "Docs", "Dev", "Planning"), { recursive: true });
  fs.writeFileSync(
    path.join(workspace, "Docs", "Dev", "Planning", "oracle_resource_labels.json"),
    JSON.stringify({ room: { "0x45": "Glacia Estate (Jail Cells)" } }),
    "utf8",
  );

  let submittedText = "";
  let submittedRefs: ConstructRef[] = [];
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: (text: string, _attachments?: AttachmentMeta[], constructRefs?: ConstructRef[]) => {
      submittedText = text;
      submittedRefs = constructRefs ?? [];
    },
  });

  try {
    await sleep(200);
    await typeText(app.stdin, "#room:gla");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("Game reference"));
    }, 4000);
    app.stdin.write("\r");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("#room:0x45"));
    }, 4000);

    await typeText(app.stdin, "inspect this room");
    app.stdin.write("\r");

    await waitFor(() => {
      assert.equal(submittedText, "inspect this room");
      assert.deepEqual(submittedRefs, [{
        kind: "room",
        query: "0x45",
        token: "#room:0x45",
        id: "0x45",
        label: "Glacia Estate (Jail Cells)",
      }]);
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput offers #object refs from sprite catalog metadata", async () => {
  const restoreTTY = setTTY(true);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "z3cli-prompt-"));
  fs.mkdirSync(path.join(workspace, "Docs", "Technical"), { recursive: true });
  fs.writeFileSync(
    path.join(workspace, "Docs", "Technical", "sprite_catalog.md"),
    [
      "## Objects (8 files)",
      "| Sprite | Status | Location | Purpose | Notes |",
      "|--------|--------|----------|---------|-------|",
      "| **Minecart** | ✅ Done | D6 (Goron Mines) | Rideable puzzle system | Complex track persistence |",
    ].join("\n"),
    "utf8",
  );

  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace,
    disabled: false,
    onSubmit: () => {},
  });

  try {
    await sleep(200);
    await typeText(app.stdin, "#object:mine");
    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("Game reference"));
      assert.ok(frame.includes("#object:minecart"));
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
    fs.rmSync(workspace, { recursive: true, force: true });
  }
});

test("PromptInput command palette submits the selected action", async () => {
  const restoreTTY = setTTY(true);
  let submitted = "";

  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace: process.cwd(),
    disabled: false,
    onSubmit: (text: string) => {
      submitted = text;
    },
  });

  try {
    await sleep(200);
    await openPalette(app);
    await typeText(app.stdin, "status");
    app.stdin.write("\r");

    await waitFor(() => {
      assert.equal(submitted, "/status");
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
  }
});

test("PromptInput opens the palette when the app triggers it", async () => {
  const restoreTTY = setTTY(true);
  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace: process.cwd(),
    disabled: false,
    paletteTrigger: 0,
    onSubmit: () => {},
  });

  try {
    await sleep(150);
    app.rerender(
      React.createElement(
        SettingsContext.Provider,
        {
          value: {
            settings: DEFAULT_SETTINGS,
            colors: getThemeColors(DEFAULT_SETTINGS.theme),
            toggleSetting: () => {},
            setSetting: () => {},
            resetSettings: () => {},
            cycleMode: () => {},
            cycleTheme: () => {},
            cycleThinkingMode: () => {},
            cycleThinkingDetail: () => {},
          },
        },
        React.createElement(PromptInput, {
          mode: "manual",
          model: "nayru",
          models: MODEL_FIXTURE,
          workspace: process.cwd(),
          disabled: false,
          paletteTrigger: 1,
          onSubmit: () => {},
        }),
      ),
    );

    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("Command palette"));
    }, 2000);
  } finally {
    app.unmount();
    restoreTTY();
  }
});

test("PromptInput honors Ctrl+A when editing the prompt", async () => {
  const restoreTTY = setTTY(true);
  let submitted = "";

  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace: process.cwd(),
    disabled: false,
    onSubmit: (text: string) => {
      submitted = text;
    },
  });

  try {
    await sleep(150);
    await typeText(app.stdin, "status");
    app.stdin.write("\x01");
    await sleep(75);
    app.stdin.write("/");
    await waitFor(() => {
      assert.ok(normalizeFrame(app.lastFrame()).includes("/status"));
    }, 2000);
    app.stdin.write("\r");

    await waitFor(() => {
      assert.equal(submitted, "/status");
    }, 4000);
  } finally {
    app.unmount();
    restoreTTY();
  }
});

test("PromptInput clears on Ctrl+C and exits on the second Ctrl+C", async () => {
  const restoreTTY = setTTY(true);
  const originalExit = process.exit;
  let exitCode: number | undefined;
  Object.defineProperty(process, "exit", {
    value: ((code?: number) => {
      exitCode = code ?? 0;
    }) as typeof process.exit,
    configurable: true,
    writable: true,
  });

  const app = renderPromptInput({
    mode: "manual",
    model: "nayru",
    models: MODEL_FIXTURE,
    workspace: process.cwd(),
    disabled: false,
    onSubmit: () => {},
  });

  try {
    await sleep(150);
    await typeText(app.stdin, "status");
    app.stdin.write("\x03");

    await waitFor(() => {
      const frame = normalizeFrame(app.lastFrame());
      assert.ok(frame.includes("Cleared. Ctrl+C again to exit"));
      assert.ok(!frame.includes("status"));
    }, 2000);

    app.stdin.write("\x03");

    await waitFor(() => {
      assert.equal(exitCode, 0);
    }, 2000);
  } finally {
    app.unmount();
    Object.defineProperty(process, "exit", {
      value: originalExit,
      configurable: true,
      writable: true,
    });
    restoreTTY();
  }
});
