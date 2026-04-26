/**
 * Command dispatch table for z3cli.
 *
 * Commands are data, not code — each entry is a named handler function.
 * App.tsx calls dispatchCommand() and awaits it; the batch runner also
 * awaits it, eliminating the duplicate if/else block that previously lived
 * in both handleSubmit and the batch useEffect.
 *
 * File-local helpers (runCmd, fmtTok) are unexported — like anonymous
 * namespace functions in the C++ side of this project.
 */

import { symbols } from "../theme/index.js";
import { shortenPath } from "../utils/path.js";
import { describeLoadedModelRuntime, formatModelMemory, modelPickerDescription } from "../utils/models.js";
import { UI_MODES, UI_THEMES, UI_THINKING_DETAILS, UI_THINKING_MODES } from "../hooks/useSettings.js";
import type { AppConfig, ConstructRef, Message, ModelInfo } from "../ipc/protocol.js";
import type { ShowThinkingMode, ThinkingDetailMode, UISettings, UIMode, UITheme } from "../hooks/useSettings.js";
import type { SubagentEntry } from "../utils/subagentState.js";

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

export interface SessionInfo {
  name: string;
  started: string;
  updated: string;
  backend: string;
  activeModel: string;
  models: string[];
  messages: number;
  mode: string;
  workspace: string;
  preview: string;
  toolCalls: number;
}

export interface CommandContext {
  config: AppConfig | null;
  settings: UISettings;
  addSystemMessage: (content: string) => void;
  replaceMessages: (messages: Message[]) => void;
  replaceSubagents: (entries: SubagentEntry[]) => void;
  updateConfig: (patch: Partial<AppConfig>) => void;
  sendCommand: (cmd: string, args?: string[]) => Promise<unknown>;
  sendMessage: (text: string) => Promise<void>;
  setSetting: (key: keyof UISettings, value: any) => void;
  resetSettings: () => void;
  openSettings: () => void;
  openHelp: () => void;
  openModelManager?: () => void;
  openSessionPicker: (sessions: SessionInfo[]) => void;
  exit: () => void;
}

type Handler = (args: string[], ctx: CommandContext) => Promise<void>;

const BOOLEAN_SETTING_KEYS: ReadonlySet<keyof UISettings> = new Set([
  "modeColoredBorder",
  "toolsIndicator",
  "showTimestamps",
  "showToolGrouping",
  "coloredToolArgs",
  "showFocusFile",
  "showBroadcastModels",
  "showDiagnostics",
  "collapseReasoning",
]);

type EnumSettingKey = "theme" | "uiMode" | "showThinking" | "thinkingDetail";

const ENUM_SETTING_KEYS = new Set<EnumSettingKey>(["theme", "uiMode", "showThinking", "thinkingDetail"]);

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

function runCmd(
  cmd: string,
  args: string[],
  ctx: CommandContext,
  handler: (result: unknown) => void,
): Promise<void> {
  return ctx
    .sendCommand(cmd, args)
    .then(handler)
    .catch((e: Error) => ctx.addSystemMessage(`Error: ${e.message}`));
}

function fmtTok(n: number): string {
  return n > 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
}

function renderLoadedModels(result: unknown): string {
  const payload = (result && typeof result === "object") ? result as Record<string, unknown> : {};
  const loadedModels = Array.isArray(payload.loaded_models)
      ? payload.loaded_models.flatMap((entry) => {
        if (!entry || typeof entry !== "object") return [];
        const model = entry as Record<string, unknown>;
        if (typeof model.identifier !== "string" || typeof model.model_key !== "string") return [];
        return [{
          identifier: model.identifier,
          modelKey: model.model_key,
          displayName: typeof model.display_name === "string" ? model.display_name : undefined,
          sizeBytes: typeof model.size_bytes === "number" ? model.size_bytes : undefined,
          status: typeof model.status === "string" ? model.status : undefined,
          parallel: typeof model.parallel === "number" ? model.parallel : undefined,
          queued: typeof model.queued === "number" ? model.queued : undefined,
          contextLength: typeof model.context_length === "number" ? model.context_length : undefined,
          quantization: typeof model.quantization === "string" ? model.quantization : undefined,
          estimatedGpuBytes: typeof model.estimated_gpu_bytes === "number" ? model.estimated_gpu_bytes : undefined,
          estimatedTotalBytes: typeof model.estimated_total_bytes === "number" ? model.estimated_total_bytes : undefined,
        }];
      })
    : [];
  if (loadedModels.length === 0) {
    return "No loaded API models reported by the active backend.";
  }
  const totalBytes = typeof payload.loaded_model_memory_bytes === "number" ? payload.loaded_model_memory_bytes : 0;
  const header = `### Loaded Models\n\n${loadedModels.length} live${totalBytes > 0 ? ` · ${formatModelMemory(totalBytes)}` : ""}`;
  const lines = loadedModels.map((model) => {
    const runtime = describeLoadedModelRuntime({
      sizeBytes: model.sizeBytes,
      status: model.status,
      parallel: model.parallel,
      queued: model.queued,
      contextLength: model.contextLength,
      quantization: model.quantization,
      estimatedGpuBytes: model.estimatedGpuBytes,
      estimatedTotalBytes: model.estimatedTotalBytes,
    });
    const label = model.identifier;
    const displayName = model.displayName && model.displayName !== label ? ` _${model.displayName}_` : "";
    return `- **${label}**${displayName}${runtime ? ` · ${runtime}` : ""}`;
  });
  return `${header}\n\n${lines.join("\n")}`;
}

function renderModelList(models: ModelInfo[], activeModel: string | undefined, title: string): string {
  if (models.length === 0) {
    return `### ${title}\n\nNo models available.`;
  }
  const lines = models.map((m) => {
    const active = m.name === activeModel ? "⚔" : " ";
    const loaded = m.loaded ? "✓" : " ";
    const tools = m.toolsEnabled ? "🔨" : " ";
    const summary = modelPickerDescription(m);
    const runtime = describeLoadedModelRuntime(m);
    return `${active} **${m.name}** · ${loaded} loaded · ${tools} tools · _${summary}_${runtime ? ` · ${runtime}` : ""}`;
  });
  return `### ${title}\n\n${lines.join("\n")}`;
}

function renderBackendStatus(result: unknown): string {
  const payload = (result && typeof result === "object") ? result as Record<string, unknown> : {};
  const totalBytes = typeof payload.loaded_model_memory_bytes === "number" ? payload.loaded_model_memory_bytes : 0;
  const loadedCount = typeof payload.loaded_model_count === "number" ? payload.loaded_model_count : 0;
  const lines = [
    `- **backend**: \`${String(payload.backend ?? "?")}\``,
    `- **connected**: \`${String(payload.connected ?? false)}\``,
  ];
  if (typeof payload.detail === "string" && payload.detail) {
    lines.push(`- **detail**: \`${payload.detail}\``);
  }
  lines.push(`- **loaded**: \`${loadedCount}\`${totalBytes > 0 ? ` (${formatModelMemory(totalBytes)})` : ""}`);
  return `### Backend Status\n\n${lines.join("\n")}`;
}

function renderSmokeResult(result: unknown): string {
  const payload = (result && typeof result === "object") ? result as Record<string, unknown> : {};
  const ok = payload.ok === true;
  const matched = payload.matched === true;
  const backend = String(payload.backend ?? "?");
  const node = typeof payload.node === "string" && payload.node ? payload.node : String(payload.api_base ?? "");
  const model = String(payload.model ?? "?");
  const duration = typeof payload.duration_ms === "number" ? `${payload.duration_ms}ms` : "?ms";
  const text = typeof payload.text === "string" ? payload.text.trim() : "";
  const error = typeof payload.error === "string" ? payload.error.trim() : "";
  if (!ok) {
    return [
      "### Smoke Failed",
      "",
      `- **backend**: \`${backend}\``,
      node ? `- **route**: \`${node}\`` : "",
      `- **model**: \`${model}\``,
      error ? `- **error**: ${error}` : "- **error**: empty response",
    ].filter(Boolean).join("\n");
  }
  return [
    "### Smoke OK",
    "",
    `- **backend**: \`${backend}\``,
    node ? `- **route**: \`${node}\`` : "",
    `- **model**: \`${model}\``,
    `- **duration**: \`${duration}\``,
    `- **expected reply**: \`${matched ? "matched" : "not matched"}\``,
    text && !matched ? `\nReply:\n\n\`\`\`\n${text}\n\`\`\`` : "",
  ].filter(Boolean).join("\n");
}

function renderRouteList(result: unknown): string {
  const payload = (result && typeof result === "object") ? result as Record<string, unknown> : {};
  const active = (payload.active && typeof payload.active === "object") ? payload.active as Record<string, unknown> : {};
  const entries = Array.isArray(payload.entries)
    ? payload.entries.flatMap((entry) => entry && typeof entry === "object" ? [entry as Record<string, unknown>] : [])
    : [];
  const activeLine = `Active: \`${String(active.backend ?? "?")}\` / \`${String(active.model ?? "?")}\``;
  if (entries.length === 0) {
    return `### Routes\n\n${activeLine}\n\nNo named routes configured.`;
  }
  const lines = entries.map((entry) => {
    const name = String(entry.name ?? "?");
    const backend = String(entry.backend ?? "?");
    const model = typeof entry.model === "string" && entry.model ? ` · ${entry.model}` : "";
    const description = typeof entry.description === "string" && entry.description ? ` · ${entry.description}` : "";
    const aliases = Array.isArray(entry.aliases)
      ? entry.aliases.map((alias) => String(alias)).filter(Boolean)
      : [];
    const aliasText = aliases.length > 0
      ? ` · aliases: ${aliases.map((alias) => `\`${alias}\``).join(", ")}`
      : "";
    const advanced = entry.advanced ? " · advanced" : "";
    return `- **${name}** · \`${backend}\`${model}${description}${aliasText}${advanced}`;
  });
  return `### Routes\n\n${activeLine}\n\n${lines.join("\n")}`;
}

function settingUsage(key: "theme" | "uiMode" | "showThinking" | "thinkingDetail"): string {
  if (key === "theme") {
    return `Usage: \`/settings theme ${UI_THEMES.join("|")}\``;
  }
  if (key === "uiMode") {
    return `Usage: \`/settings uiMode ${UI_MODES.join("|")}\``;
  }
  if (key === "showThinking") {
    return `Usage: \`/settings showThinking ${UI_THINKING_MODES.join("|")}\``;
  }
  return `Usage: \`/settings thinkingDetail ${UI_THINKING_DETAILS.join("|")}\``;
}

function parseEnumSetting(
  key: "theme" | "uiMode" | "showThinking" | "thinkingDetail",
  rawValue: string | undefined,
): UITheme | UIMode | ShowThinkingMode | ThinkingDetailMode | null {
  const value = rawValue?.trim().toLowerCase();
  if (!value) return null;
  if (key === "theme") {
    if (UI_THEMES.includes(value as UITheme)) return value as UITheme;
    // Accept legacy theme names ("gold" → hyrule, "red" → subrosia, ...).
    const legacyMap: Record<string, UITheme> = {
      gold:  "hyrule",
      red:   "subrosia",
      blue:  "labrynna",
      green: "labrynna",
    };
    return legacyMap[value] ?? null;
  }
  if (key === "uiMode") {
    return UI_MODES.includes(value as UIMode) ? (value as UIMode) : null;
  }
  if (key === "showThinking") {
    return UI_THINKING_MODES.includes(value as ShowThinkingMode)
      ? (value as ShowThinkingMode)
      : null;
  }
  return UI_THINKING_DETAILS.includes(value as ThinkingDetailMode)
    ? (value as ThinkingDetailMode)
    : null;
}

function normalizeMessages(raw: unknown): Message[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry, index) => {
    if (!entry || typeof entry !== "object") return [];
    const msg = entry as Record<string, unknown>;
    const role = msg.role;
    if (role !== "user" && role !== "assistant" && role !== "system" && role !== "tool") {
      return [];
    }
    const normalizeConstructRef = (item: unknown): ConstructRef | null => {
      if (!item || typeof item !== "object") return null;
      const entry = item as Record<string, unknown>;
      if (typeof entry.kind !== "string" || typeof entry.query !== "string") {
        return null;
      }
      return {
        kind: entry.kind,
        query: entry.query,
        ...(typeof entry.token === "string" ? { token: entry.token } : {}),
        ...(typeof entry.id === "string" ? { id: entry.id } : {}),
        ...(typeof entry.label === "string" ? { label: entry.label } : {}),
      };
    };
      return [{
        id: typeof msg.id === "string" ? msg.id : `restored-${index}`,
        role,
        content: typeof msg.content === "string" ? msg.content : "",
      thinking: typeof msg.thinking === "string" && msg.thinking ? msg.thinking : undefined,
      model: typeof msg.model === "string" ? msg.model : undefined,
      toolName: typeof msg.toolName === "string" ? msg.toolName : undefined,
      toolServer: typeof msg.toolServer === "string" ? msg.toolServer : undefined,
      toolArguments: typeof msg.toolArguments === "string" ? msg.toolArguments : undefined,
      timestamp: typeof msg.timestamp === "number" ? msg.timestamp : Date.now(),
        turnId: typeof msg.turnId === "string" ? msg.turnId : undefined,
        toolGroup: typeof msg.toolGroup === "string" ? msg.toolGroup : undefined,
        requestId: typeof msg.requestId === "string" ? msg.requestId : undefined,
        spanId: typeof msg.spanId === "string" ? msg.spanId : undefined,
        attachments: Array.isArray(msg.attachments)
          ? msg.attachments.flatMap((item) => {
              if (!item || typeof item !== "object") return [];
              const entry = item as Record<string, unknown>;
              if (typeof entry.path !== "string") {
                return [];
              }
              return [{
                path: entry.path,
                lines: typeof entry.lines === "number" ? entry.lines : 0,
                chars: typeof entry.chars === "number" ? entry.chars : 0,
              }];
            })
          : undefined,
        constructRefs: Array.isArray(msg.constructRefs)
          ? msg.constructRefs.map(normalizeConstructRef).flatMap((item) => (item ? [item] : []))
          : Array.isArray(msg.construct_refs)
            ? msg.construct_refs.map(normalizeConstructRef).flatMap((item) => (item ? [item] : []))
            : undefined,
      }];
  });
}

export function normalizeSubagents(raw: unknown): SubagentEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const item = entry as Record<string, unknown>;
    if (
      typeof item.id !== "string"
      || typeof item.name !== "string"
      || typeof item.model !== "string"
      || typeof item.provider !== "string"
      || typeof item.depth !== "number"
      || (item.status !== "running" && item.status !== "done" && item.status !== "error" && item.status !== "cancelled")
      || typeof item.text !== "string"
      || typeof item.thinking !== "string"
      || typeof item.toolCallCount !== "number"
      || typeof item.startedAt !== "number"
    ) {
      return [];
    }
    return [{
      id: item.id,
      name: item.name,
      model: item.model,
      provider: item.provider,
      depth: item.depth,
      parentId: typeof item.parentId === "string" ? item.parentId : undefined,
      status: item.status,
      text: item.text,
      thinking: item.thinking,
      toolCallCount: item.toolCallCount,
      activeTool:
        item.activeTool && typeof item.activeTool === "object"
          && typeof (item.activeTool as Record<string, unknown>).name === "string"
          && typeof (item.activeTool as Record<string, unknown>).server === "string"
          ? {
              name: (item.activeTool as Record<string, unknown>).name as string,
              server: (item.activeTool as Record<string, unknown>).server as string,
            }
          : undefined,
      startedAt: item.startedAt,
      finishedAt: typeof item.finishedAt === "number" ? item.finishedAt : undefined,
      error: typeof item.error === "string" ? item.error : undefined,
      promptTokens: typeof item.promptTokens === "number" ? item.promptTokens : undefined,
      completionTokens: typeof item.completionTokens === "number" ? item.completionTokens : undefined,
    }];
  });
}

export function normalizeSessions(raw: Array<Record<string, unknown>>): SessionInfo[] {
  return raw.map((s) => ({
    name: String(s.name ?? ""),
    started: String(s.started ?? ""),
    updated: String(s.updated ?? s.started ?? ""),
    backend: String(s.backend ?? "studio"),
    activeModel: String(s.active_model ?? "?"),
    models: Array.isArray(s.models) ? (s.models as string[]) : [],
    messages: typeof s.messages === "number" ? s.messages : 0,
    mode: String(s.mode ?? "manual"),
    workspace: String(s.workspace ?? ""),
    preview: String(s.preview ?? ""),
    toolCalls: typeof s.tool_calls === "number" ? s.tool_calls : 0,
  }));
}

export async function executeShell(cmd: string, ctx: CommandContext): Promise<void> {
  if (!cmd) return;
  try {
    const result = await ctx.sendCommand("/shell", [cmd]) as {
      output?: string;
      exit_code?: number;
      cwd?: string;
      duration_ms?: number;
    } | null;
    ctx.updateConfig({
      shellActive: true,
      shellCwd: result?.cwd ?? ctx.config?.workspace,
    });
    const output = result?.output?.trimEnd() || "(no output)";
    const cwd = result?.cwd ? `cwd: ${shortenPath(result.cwd)}` : "";
    const exitCode = typeof result?.exit_code === "number" ? `exit: ${result.exit_code}` : "";
    const duration = typeof result?.duration_ms === "number" ? `${result.duration_ms}ms` : "";
    const footer = [cwd, exitCode, duration].filter(Boolean).join("  ");
    ctx.addSystemMessage(
      ["```", output, "```", footer].filter(Boolean).join("\n"),
    );
  } catch (e) {
    const err = e as Error;
    ctx.addSystemMessage(`Error: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Command table
// ---------------------------------------------------------------------------

const COMMANDS: Record<string, Handler> = {
  "/exit": async (_, ctx) => ctx.exit(),

  "/help": async (_, ctx) => ctx.openHelp(),

  "/oracle-tips": (args, ctx) =>
    runCmd("/oracle-tips", args, ctx, (result) => {
      const r = result as { title?: string; text?: string } | null;
      if (r?.text) {
        const title = r.title ? `### ${r.title}\n\n` : "";
        ctx.addSystemMessage(`${title}${r.text}`);
      } else {
        ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```");
      }
    }),

  "/model-manager": async (_, ctx) => ctx.openModelManager?.(),

  "/models": async (args, ctx) => {
    if (!ctx.config) return;
    const subcommand = (args[0] || "").toLowerCase();
    if (!subcommand || subcommand === "list") {
      ctx.addSystemMessage(renderModelList(ctx.config.models, ctx.config.activeModel, "Available Models"));
      return;
    }
    if (subcommand === "catalog") {
      ctx.addSystemMessage(renderModelList(ctx.config.modelCatalog ?? ctx.config.models, ctx.config.activeModel, "Model Catalog"));
      return;
    }
    if (subcommand === "loaded") {
      const result = await ctx.sendCommand("/models", ["loaded"]);
      ctx.addSystemMessage(renderLoadedModels(result));
      return;
    }
    if (subcommand === "routes" || subcommand === "route") {
      const result = await ctx.sendCommand("/models", args.length > 0 ? args : ["routes"]);
      ctx.addSystemMessage(renderRouteList(result));
      return;
    }
    ctx.addSystemMessage("Usage: `/models [list|catalog|loaded|routes [advanced|--all]]`");
  },

  "/modes": async (_, ctx) =>
    ctx.addSystemMessage(
      "**Routing modes:** manual (active model only), oracle (portfolio router), " +
      "orchestrator (planner delegates to specialists), broadcast (fan out to multiple models)",
    ),

  "/settings": async (args, ctx) => {
    if (!args[0]) {
      ctx.openSettings();
      return;
    }
    if (args[0] === "reset") {
      ctx.resetSettings();
      ctx.addSystemMessage("UI settings reset to defaults.");
      return;
    }
    const key = args[0] as keyof UISettings;
    if (BOOLEAN_SETTING_KEYS.has(key)) {
      const val = args[1]?.toLowerCase();
      if (val === "on" || val === "off") {
        ctx.setSetting(key, val === "on");
        ctx.addSystemMessage(`Setting **${key}** → **${val}**`);
      } else {
        ctx.addSystemMessage(
          `**${key}** is currently **${ctx.settings[key] ? "on" : "off"}**\n\n` +
          `Usage: \`/settings ${key} on|off\``,
        );
      }
      return;
    }
    if (ENUM_SETTING_KEYS.has(args[0] as EnumSettingKey)) {
      const enumKey = args[0] as EnumSettingKey;
      const nextValue = parseEnumSetting(enumKey, args[1]);
      if (nextValue !== null) {
        ctx.setSetting(enumKey, nextValue);
        ctx.addSystemMessage(`Setting **${enumKey}** → **${nextValue}**`);
      } else {
        ctx.addSystemMessage(
          `**${enumKey}** is currently **${ctx.settings[enumKey]}**\n\n${settingUsage(enumKey)}`,
        );
      }
      return;
    }
    ctx.addSystemMessage(
      `Unknown setting: \`${args[0]}\`\n\n` +
      "Run `/settings` to open the settings panel or `/settings reset` to restore defaults.",
    );
  },

  "/model": (args, ctx) =>
    runCmd("/model", args, ctx, (result) => {
      const r = result as { active_model?: string } | null;
      if (r?.active_model) {
        ctx.updateConfig({ activeModel: r.active_model });
        ctx.addSystemMessage(`Model set to **${r.active_model}**`);
      }
    }),

  "/orchestrator": (args, ctx) =>
    runCmd("/orchestrator", args, ctx, (result) => {
      const r = result as {
        orchestrator?: string;
        resolved?: string;
        auto_selected?: boolean;
        warning?: string;
      } | null;
      if (r) {
        ctx.updateConfig({
          orchestratorModel: typeof r.orchestrator === "string" ? r.orchestrator : ctx.config?.orchestratorModel,
        });
        const planner = r.orchestrator || "(auto)";
        const resolved = r.resolved ? `resolved: **${r.resolved}**` : "resolved: **none**";
        const auto = r.auto_selected ? "auto-selected" : "explicit";
        ctx.addSystemMessage(`Orchestrator planner: **${planner}** (${auto}, ${resolved})`);
        if (r.warning) {
          ctx.addSystemMessage(`Warning: ${r.warning}`);
        }
      }
    }),

  "/backend": (args, ctx) =>
    runCmd("/backend", args, ctx, (result) => {
      const r = result as { backend?: string; active_model?: string; model?: string } | null;
      if (r?.backend) {
        ctx.updateConfig({
          backend: r.backend,
          activeModel: r.active_model ?? r.model ?? ctx.config?.activeModel,
        });
        ctx.addSystemMessage(
          `Backend set to **${r.backend}**${r.active_model ? ` (${r.active_model})` : ""}`,
        );
      }
    }),

  "/route": (args, ctx) =>
    {
      const subcommand = (args[0] || "").toLowerCase();
      if (args[0] && !["list", "ls", "current", "status", "preview", "smoke", "doctor", "health"].includes(subcommand)) {
        ctx.addSystemMessage(`Switching route to **${args[0]}**...`);
      } else if (["smoke", "doctor", "health"].includes(subcommand)) {
        ctx.addSystemMessage(`Probing **${args[1] || "current route"}**...`);
      }
      return runCmd("/route", args, ctx, (result) => {
        const r = result as {
          active?: unknown;
          entries?: unknown[];
          backend?: string;
          model?: string;
          route?: string;
          resolved?: string;
          ok?: boolean;
        } | null;
        if (r && "ok" in r) {
          ctx.addSystemMessage(renderSmokeResult(result));
        } else if (r?.backend) {
          ctx.updateConfig({
            backend: r.backend,
            activeModel: r.model ?? ctx.config?.activeModel,
          });
          const label = r.route || args[0] || r.resolved || r.model || r.backend;
          ctx.addSystemMessage(`Route set to **${label}** via **${r.backend}**${r.model ? ` (${r.model})` : ""}`);
        } else if (r && (Array.isArray(r.entries) || r.active)) {
          ctx.addSystemMessage(renderRouteList(result));
        } else {
          ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```");
        }
      });
    },

  "/use": (args, ctx) =>
    {
      if (args[0]) {
        ctx.addSystemMessage(`Switching route to **${args[0]}**...`);
      }
      return runCmd("/use", args, ctx, (result) => {
      const r = result as {
        active?: unknown;
        entries?: unknown[];
        backend?: string;
        model?: string;
        route?: string;
        resolved?: string;
        studio_node?: string;
        llamacpp_node?: string;
      } | null;
      if (r?.backend) {
        ctx.updateConfig({
          backend: r.backend,
          activeModel: r.model ?? ctx.config?.activeModel,
        });
        const label = r.route || r.resolved || args[0] || r.model || r.backend;
        ctx.addSystemMessage(`Using **${label}** via **${r.backend}**${r.model ? ` (${r.model})` : ""}`);
      } else if (r && (Array.isArray(r.entries) || r.active)) {
        ctx.addSystemMessage(renderRouteList(result));
      } else {
        ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```");
      }
      });
    },

  "/backends": (args, ctx) =>
    runCmd("/backends", args, ctx, (result) =>
      ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```"),
    ),

  "/backend-status": (args, ctx) =>
    runCmd("/backend-status", args, ctx, (result) =>
      ctx.addSystemMessage(renderBackendStatus(result)),
    ),

  "/smoke": async (args, ctx) => {
    const target = args[0] || "current route";
    ctx.addSystemMessage(`Probing **${target}**...`);
    return runCmd("/smoke", args, ctx, (result) =>
      ctx.addSystemMessage(renderSmokeResult(result)),
    );
  },

  "/doctor": async (args, ctx) => {
    const target = args[0] || "current route";
    ctx.addSystemMessage(`Probing **${target}**...`);
    return runCmd("/doctor", args, ctx, (result) =>
      ctx.addSystemMessage(renderSmokeResult(result)),
    );
  },

  "/loaded": (args, ctx) =>
    runCmd("/loaded", args, ctx, (result) =>
      ctx.addSystemMessage(renderLoadedModels(result)),
    ),

  "/load": (args, ctx) =>
    runCmd("/load", args, ctx, (result) => {
      const r = result as { loaded?: string; warning?: string } | null;
      if (r?.loaded) {
        ctx.addSystemMessage(`Loaded **${r.loaded}**.`);
      }
      if (r?.warning) {
        ctx.addSystemMessage(`Warning: ${r.warning}`);
      }
    }),

  "/mode": (args, ctx) =>
    runCmd("/mode", args, ctx, (result) => {
      const r = result as { mode?: string } | null;
      if (r?.mode) {
        ctx.updateConfig({ mode: r.mode });
        ctx.addSystemMessage(`Mode set to **${r.mode}**`);
      }
    }),

  "/status": (args, ctx) =>
    runCmd("/status", args, ctx, (result) => {
      const r = result as Record<string, unknown> | null;
      if (r) {
        const out = Object.entries(r)
          .map(([k, v]) => `* **${k}**: \`${JSON.stringify(v)}\``)
          .join("\n");
        ctx.addSystemMessage(`### Backend Status\n\n${out}`);
      }
    }),

  "/reset": (args, ctx) =>
    runCmd("/reset", args, ctx, () => {
      ctx.addSystemMessage(
        `History cleared for ${args[0] || ctx.config?.activeModel || "current model"}.`,
      );
    }),

  "/unload": (args, ctx) =>
    runCmd("/unload", args, ctx, (result) => {
      const r = result as { target?: string; unloaded?: string[]; all?: boolean; warning?: string } | null;
      const unloaded = Array.isArray(r?.unloaded) ? r.unloaded : [];
      if (r?.all) {
        ctx.addSystemMessage(`Unloaded **all** models${unloaded.length > 0 ? ` (${unloaded.length})` : ""}.`);
      } else {
        ctx.addSystemMessage(`Unloaded **${unloaded[0] ?? r?.target ?? args[0] ?? ctx.config?.activeModel ?? "model"}**.`);
      }
      if (r?.warning) {
        ctx.addSystemMessage(`Warning: ${r.warning}`);
      }
    }),

  "/tools": (args, ctx) => {
    const enabled = args[0]?.toLowerCase() === "on";
    return runCmd("/tools", args, ctx, () => {
      ctx.updateConfig({ toolsEnabled: enabled });
      ctx.addSystemMessage(`Tools ${enabled ? "enabled" : "disabled"}.`);
    });
  },

  "/tools-write": (args, ctx) => {
    const enabled = args[0]?.toLowerCase() === "on";
    return runCmd("/tools-write", args, ctx, () => {
      ctx.updateConfig({ toolsWrite: enabled });
      ctx.addSystemMessage(`Tool write access ${enabled ? "enabled" : "disabled"}.`);
    });
  },

  "/verify-hooks": (args, ctx) => {
    const enabled = args[0]?.toLowerCase() === "on";
    return runCmd("/verify-hooks", args, ctx, () => {
      ctx.updateConfig({ verifyHooks: enabled });
      ctx.addSystemMessage(`Automatic verification ${enabled ? "enabled" : "disabled"}.`);
    });
  },

  "/servers": async (_, ctx) => {
    if (!ctx.config) return;
    const servers = ctx.config.servers.length > 0
      ? ctx.config.servers.map((s) => `* ${s}`).join("\n")
      : "_No tool servers connected._";
    const warnings = ctx.config.warnings.length > 0
      ? `\n\n**Warnings:**\n${ctx.config.warnings.map((w) => `* ${w}`).join("\n")}`
      : "";

    ctx.addSystemMessage(
      `### Tool Environment\n\n` +
      `**Active Servers:**\n${servers}\n\n` +
      `**Total Tools:** ${ctx.config.toolCount}` +
      warnings,
    );
  },

  "/focus": async (args, ctx) => {
    if (!args[0]) {
      return runCmd("/focus", [], ctx, (result) => {
        const r = result as { active?: boolean; lines?: number; chars?: number } | null;
        if (r?.active) {
          ctx.addSystemMessage(
            `Focus active: **${r.lines}** lines, **${r.chars}** chars in system prompt.\n` +
            `Use \`/focus clear\` to remove.`,
          );
        } else {
          ctx.addSystemMessage(
            "**Usage:** `/focus <path|clear>`\n\n" +
            "Load a file into the system prompt prefix where it gets KV-cached.\n" +
            "Subsequent turns reuse the cached context for free.\n\n" +
            "| Example | Effect |\n|---------|--------|\n" +
            "| `/focus Core/ram.asm` | Load relative to workspace |\n" +
            "| `/focus ~/src/hobby/usdasm/bank_06.asm` | Load absolute path |\n" +
            "| `/focus clear` | Remove focus context |",
          );
        }
      });
    }
    if (args[0].toLowerCase() === "clear") {
      return runCmd("/focus", args, ctx, () => {
        ctx.updateConfig({ focusFile: undefined });
        ctx.addSystemMessage("Focus context cleared.");
      });
    }
    ctx.addSystemMessage(`Loading **${args[0]}** into focus context...`);
    return runCmd("/focus", args, ctx, (result) => {
      const r = result as { loaded?: string; path?: string; lines?: number; chars?: number } | null;
      if (r?.loaded) {
        ctx.updateConfig({ focusFile: r.path ?? r.loaded });
        ctx.addSystemMessage(
          `Loaded **${r.loaded}** (${r.lines} lines, ${r.chars} chars) into system prompt.\n` +
          `This context is now KV-cached — all subsequent turns benefit from it.`,
        );
      }
    });
  },

  "/permissions": (args, ctx) =>
    runCmd("/permissions", args, ctx, (result) => {
      const r = result as { cleared?: boolean; allow?: string[]; deny?: string[] } | null;
      if (r?.cleared) {
        ctx.updateConfig({ permissionRules: {} });
        ctx.addSystemMessage("Sticky permission rules cleared.");
        return;
      }
      const allow = r?.allow ?? [];
      const deny = r?.deny ?? [];
      if (allow.length === 0 && deny.length === 0) {
        ctx.addSystemMessage("No sticky permission rules.");
        return;
      }
      const lines = ["**Sticky permission rules**"];
      if (allow.length > 0) {
        lines.push("", `Allow: ${allow.join(", ")}`);
      }
      if (deny.length > 0) {
        lines.push("", `Deny: ${deny.join(", ")}`);
      }
      ctx.addSystemMessage(lines.join("\n"));
    }),

  "/stats": (args, ctx) =>
    runCmd("/stats", args, ctx, (result) => {
      const r = result as Record<string, unknown> | null;
      if (!r) return;
      const pt = (r.prompt_tokens as number) || 0;
      const ct = (r.completion_tokens as number) || 0;
      const total = pt + ct;
      const modelsUsed = (r.models_used as string[]) || [];
      const toolCalls = (r.tool_calls as number) || 0;
      const engines = (r.engines as number) || 0;
      const cancelCount = (r.cancel_count as number) || 0;
      const backendRestarts = (r.backend_restart_count as number) || 0;
      const toolLatencyMs = (r.tool_latency_ms as number) || 0;
      const toolLatencySamples = (r.tool_latency_samples as number) || 0;
      const permissionWaitMs = (r.permission_wait_ms as number) || 0;
      const reviewWaitMs = (r.review_wait_ms as number) || 0;
      const permissionTimeouts = (r.permission_timeout_count as number) || 0;
      const reviewTimeouts = (r.review_timeout_count as number) || 0;
      const modelRetryCount = (r.model_retry_count as number) || 0;
      const modelRetryBackoffMs = (r.model_retry_backoff_ms as number) || 0;
      const modelErrorCount = (r.model_error_count as number) || 0;
      const toolTimeoutCount = (r.tool_timeout_count as number) || 0;
      const modelBackpressureCount = (r.model_backpressure_count as number) || 0;
      const toolBackpressureCount = (r.tool_backpressure_count as number) || 0;
      const inflightModelCalls = (r.inflight_model_calls as number) || 0;
      const queuedModelCalls = (r.queued_model_calls as number) || 0;
      const inflightToolCalls = (r.inflight_tool_calls as number) || 0;
      const queuedToolCalls = (r.queued_tool_calls as number) || 0;
      const modelQueueHighwater = (r.model_queue_highwater as number) || 0;
      const toolQueueHighwater = (r.tool_queue_highwater as number) || 0;
      const modelRetryMax = (r.model_retry_max as number) || 0;
      const modelRetryBaseMs = (r.model_retry_base_ms as number) || 0;
      const toolExecTimeoutS = (r.tool_exec_timeout_s as number) || 0;
      const maxInflightModelCalls = (r.max_inflight_model_calls as number) || 0;
      const maxInflightTools = (r.max_inflight_tools as number) || 0;
      const execQueueDepth = (r.exec_queue_depth as number) || 0;
      const requestCount = (r.request_count as number) || 0;
      const requestSuccessCount = (r.request_success_count as number) || 0;
      const requestErrorCount = (r.request_error_count as number) || 0;
      const requestRejectCount = (r.request_reject_count as number) || 0;
      const requestCancelCount = (r.request_cancel_count as number) || 0;
      const spanCount = (r.span_count as number) || 0;
      const lastRequestId = (r.last_request_id as string) || "";
      const lastSpanId = (r.last_span_id as string) || "";
      const lastToolCallId = (r.last_tool_call_id as string) || "";
      const requestSamples = (r.request_samples as number) || 0;
      const queuedMsP50 = (r.queued_ms_p50 as number) || 0;
      const queuedMsP95 = (r.queued_ms_p95 as number) || 0;
      const modelMsP50 = (r.model_ms_p50 as number) || 0;
      const modelMsP95 = (r.model_ms_p95 as number) || 0;
      const toolMsP50 = (r.tool_ms_p50 as number) || 0;
      const toolMsP95 = (r.tool_ms_p95 as number) || 0;
      const totalMsP50 = (r.total_ms_p50 as number) || 0;
      const totalMsP95 = (r.total_ms_p95 as number) || 0;
      const lastRequestStatus = (r.last_request_status as string) || "";
      const lastRequestQueuedMs = (r.last_request_queued_ms as number) || 0;
      const lastRequestModelMs = (r.last_request_model_ms as number) || 0;
      const lastRequestToolMs = (r.last_request_tool_ms as number) || 0;
      const lastRequestTotalMs = (r.last_request_total_ms as number) || 0;

      let out = "**Session Statistics**\n\n| Metric | Value |\n|--------|-------|\n";
      out += `| Messages | ${r.messages} |\n`;
      out += `| Tool calls | ${toolCalls} |\n`;
      out += `| Prompt tokens | ${fmtTok(pt)} |\n`;
      out += `| Completion tokens | ${fmtTok(ct)} |\n`;
      out += `| **Total tokens** | **${fmtTok(total)}** |\n`;
      out += `| Cancels | ${cancelCount} |\n`;
      out += `| Backend restarts | ${backendRestarts} |\n`;
      out += `| Avg tool latency | ${toolLatencyMs}ms (${toolLatencySamples} samples) |\n`;
      out += `| Permission wait | ${permissionWaitMs}ms |\n`;
      out += `| Review wait | ${reviewWaitMs}ms |\n`;
      out += `| Permission timeouts | ${permissionTimeouts} |\n`;
      out += `| Review timeouts | ${reviewTimeouts} |\n`;
      out += `| Model retries | ${modelRetryCount} |\n`;
      out += `| Retry backoff | ${modelRetryBackoffMs}ms |\n`;
      out += `| Model errors | ${modelErrorCount} |\n`;
      out += `| Tool timeouts | ${toolTimeoutCount} |\n`;
      out += `| Model inflight/queue | ${inflightModelCalls}/${maxInflightModelCalls} · ${queuedModelCalls}/${execQueueDepth} |\n`;
      out += `| Tool inflight/queue | ${inflightToolCalls}/${maxInflightTools} · ${queuedToolCalls}/${execQueueDepth} |\n`;
      out += `| Queue highwater (m/t) | ${modelQueueHighwater}/${toolQueueHighwater} |\n`;
      out += `| Backpressure (m/t) | ${modelBackpressureCount}/${toolBackpressureCount} |\n`;
      out += `| Retry policy | max ${modelRetryMax}, base ${modelRetryBaseMs}ms |\n`;
      out += `| Tool timeout policy | ${toolExecTimeoutS}s |\n`;
      out += `| Requests | total ${requestCount} · ok ${requestSuccessCount} · err ${requestErrorCount} · rejected ${requestRejectCount} · cancelled ${requestCancelCount} |\n`;
      out += `| Spans | ${spanCount} |\n`;
      out += `| Request latency p50 (q/m/t) | ${queuedMsP50}/${modelMsP50}/${toolMsP50} ms |\n`;
      out += `| Request latency p95 (q/m/t) | ${queuedMsP95}/${modelMsP95}/${toolMsP95} ms |\n`;
      out += `| Request latency p50/p95 (total) | ${totalMsP50}/${totalMsP95} ms (n=${requestSamples}) |\n`;
      if (lastRequestStatus) {
        out += `| Last request outcome | ${lastRequestStatus} (${lastRequestQueuedMs}/${lastRequestModelMs}/${lastRequestToolMs}/${lastRequestTotalMs} ms q/m/t/total) |\n`;
      }
      if (lastRequestId) out += `| Last request id | ${lastRequestId} |\n`;
      if (lastSpanId) out += `| Last span id | ${lastSpanId} |\n`;
      if (lastToolCallId) out += `| Last tool call id | ${lastToolCallId} |\n`;
      if (engines > 0) out += `| Active engines | ${engines} |\n`;
      if (modelsUsed.length > 0) out += `| Models used | ${modelsUsed.join(", ")} |\n`;
      out += `| Session | \`${r.session || "none"}\` |`;
      ctx.addSystemMessage(out);
    }),

  "/save": (args, ctx) =>
    runCmd("/save", args, ctx, (result) => {
      const r = result as { path?: string; messages?: number } | null;
      if (r?.path) {
        const short = shortenPath(String(r.path));
        ctx.addSystemMessage(`Session auto-saving to:\n\`${short}\`\nMessages: ${r.messages}`);
      } else {
        ctx.addSystemMessage("No active session.");
      }
    }),

  "/shell": (args, ctx) => {
    if (args.length === 0) {
      return runCmd("/shell", [], ctx, (result) => {
        const r = result as { active?: boolean; cwd?: string; entries?: number } | null;
        ctx.addSystemMessage(
          `Shell ${r?.active ? "active" : "idle"}\n` +
          `${r?.cwd ? `cwd: \`${shortenPath(r.cwd)}\`\n` : ""}` +
          `${typeof r?.entries === "number" ? `history: ${r.entries}` : ""}`,
        );
      });
    }
    return executeShell(args.join(" "), ctx);
  },

  "/shell-reset": (args, ctx) =>
    runCmd("/shell-reset", args, ctx, () => {
      ctx.updateConfig({ shellActive: false, shellCwd: ctx.config?.workspace });
      ctx.addSystemMessage("Persistent shell reset.");
    }),

  "/shell-log": (args, ctx) =>
    runCmd("/shell-log", args, ctx, (result) => {
      const entries = ((result as { entries?: Array<Record<string, unknown>> } | null)?.entries ?? []);
      if (entries.length === 0) {
        ctx.addSystemMessage("No shell history.");
        return;
      }
      const lines = entries.map((entry) => {
        const command = String(entry.command ?? "");
        const exitCode = String(entry.exit_code ?? "");
        const cwd = String(entry.cwd ?? "");
        return `$ ${command}\nexit ${exitCode}${cwd ? ` · ${shortenPath(cwd)}` : ""}`;
      });
      ctx.addSystemMessage("```\n" + lines.join("\n\n") + "\n```");
    }),

  "/sessions": (args, ctx) =>
    runCmd("/sessions", args, ctx, (result) => {
      const r = result as { sessions?: Array<Record<string, unknown>> } | null;
      const raw = r?.sessions ?? [];
      if (raw.length === 0) {
        ctx.addSystemMessage("No saved sessions.");
        return;
      }
      ctx.openSessionPicker(normalizeSessions(raw));
    }),

  "/resume": async (args, ctx) => {
    if (!args[0]) {
      // No name given — open the picker instead.
      return runCmd("/sessions", [], ctx, (result) => {
        const r = result as { sessions?: Array<Record<string, unknown>> } | null;
        const raw = r?.sessions ?? [];
        if (raw.length === 0) {
          ctx.addSystemMessage("No saved sessions.");
          return;
        }
        ctx.openSessionPicker(normalizeSessions(raw));
      });
    }
    return runCmd("/resume", args, ctx, (result) => {
      const r = result as {
        resumed?: string;
        models?: string[];
        messages_restored?: number;
        messages?: unknown;
        subagents?: unknown;
        warnings?: string[];
        thinking_stripped?: boolean;
      } | null;
      if (r?.resumed) {
        ctx.replaceMessages(normalizeMessages(r.messages));
        ctx.replaceSubagents(normalizeSubagents(r.subagents));
        ctx.addSystemMessage(`Resumed **${r.resumed}** — ${r.messages_restored} messages restored`);
        if (r.thinking_stripped) {
          ctx.addSystemMessage("Resumed transcript without saved reasoning traces.");
        }
        for (const warning of r.warnings ?? []) {
          ctx.addSystemMessage(`Warning: ${warning}`);
        }
      }
    });
  },

  "/compact": async (args, ctx) => {
    const target = args[0] || ctx.config?.activeModel || "current model";
    ctx.addSystemMessage(`Compacting **${target}** history... (this calls the model for summarization)`);
    return runCmd("/compact", args, ctx, (result) => {
      const r = result as { model?: string; replaced?: number; summary_length?: number } | null;
      if (r?.model) {
        const pct =
          r.replaced && r.summary_length
            ? ` (~${Math.round((1 - r.summary_length / (r.replaced * 200)) * 100)}% reduction)`
            : "";
        ctx.addSystemMessage(
          `Compacted **${r.model}**: ${r.replaced} messages ${symbols.arrow} ${r.summary_length} char summary${pct}\n\n` +
          `*Note: compact is lossy — exact tool calls and multi-round state are not preserved.*`,
        );
      }
    });
  },
};

// Aliases — resolved before table lookup.
const ALIASES: Record<string, string> = {
  "/quit": "/exit",
  "/bye": "/exit",
};

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

export async function dispatchCommand(
  rawCmd: string,
  args: string[],
  ctx: CommandContext,
): Promise<void> {
  const cmd = rawCmd.toLowerCase();
  const resolved = ALIASES[cmd] ?? cmd;
  const handler = COMMANDS[resolved];

  if (handler) {
    return handler(args, ctx);
  }

  // Unknown command → forward to backend
  return runCmd(cmd, args, ctx, (result) => {
    if (result && typeof result === "object" && "ok" in (result as Record<string, unknown>)) {
      ctx.addSystemMessage(`${cmd} done.`);
    } else if (result) {
      ctx.addSystemMessage("```\n" + JSON.stringify(result, null, 2) + "\n```");
    }
  });
}
