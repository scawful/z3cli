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

import { exec } from "node:child_process";
import { promisify } from "node:util";
import { symbols } from "../theme/index.js";
import { DEFAULT_SETTINGS } from "../hooks/useSettings.js";
import type { AppConfig } from "../ipc/protocol.js";
import type { UISettings } from "../hooks/useSettings.js";

const execAsync = promisify(exec);

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

export interface SessionInfo {
  name: string;
  started: string;
  activeModel: string;
  models: string[];
  messages: number;
  mode: string;
}

export interface CommandContext {
  config: AppConfig | null;
  settings: UISettings;
  addSystemMessage: (content: string) => void;
  updateConfig: (patch: Partial<AppConfig>) => void;
  sendCommand: (cmd: string, args?: string[]) => Promise<unknown>;
  sendMessage: (text: string) => Promise<void>;
  setSetting: (key: keyof UISettings, value: boolean) => void;
  resetSettings: () => void;
  openSettings: () => void;
  openSessionPicker: (sessions: SessionInfo[]) => void;
  exit: () => void;
}

type Handler = (args: string[], ctx: CommandContext) => Promise<void>;

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

export async function executeShell(cmd: string, ctx: CommandContext): Promise<void> {
  if (!cmd) return;
  const cwd = ctx.config?.workspace ?? process.cwd();
  try {
    const { stdout, stderr } = await execAsync(cmd, { cwd, timeout: 30_000 });
    const out = [stdout.trimEnd(), stderr.trimEnd()].filter(Boolean).join("\n");
    ctx.addSystemMessage(out || "(no output)");
  } catch (e) {
    const err = e as { message: string; stdout?: string; stderr?: string };
    const out = [err.stdout?.trimEnd(), err.stderr?.trimEnd()].filter(Boolean).join("\n");
    ctx.addSystemMessage(`Error: ${err.message}${out ? `\n${out}` : ""}`);
  }
}

// ---------------------------------------------------------------------------
// Help text
// ---------------------------------------------------------------------------

export const HELP_TEXT = `**Commands**

| Command | Description |
|---------|-------------|
| /help | Show this help |
| /backend [name] | Show or set backend |
| /backends | List available backends |
| /backend-status | Show backend connection status |
| /model <name> | Switch active model |
| /mode <name> | Set routing mode |
| /models | List Zelda models |
| /status | Connection and state info |
| /servers | Tool server info |
| /tools <on\\|off> | Toggle tool use |
| /route <prompt> | Preview routing |
| /broadcast <a,b,c> | Set broadcast models |
| /load [name] | Load model in LM Studio |
| /loaded | List loaded API models |
| /workspace <path> | Change workspace |
| /rom <path\\|none> | Change ROM target |
| /focus <path\\|clear> | Load file into system prompt (KV-cached) |
| /reset [model\\|all] | Clear history |
| /stats | Session statistics |
| /save | Show session file path |
| /sessions | List saved sessions |
| /resume <name> | Resume a saved session |
| /compact [model] | Compress history (lossy) |
| /settings | Open UI settings panel |
| /exit | Quit z3cli |`;

// ---------------------------------------------------------------------------
// Command table
// ---------------------------------------------------------------------------

const COMMANDS: Record<string, Handler> = {
  "/exit": async (_, ctx) => ctx.exit(),

  "/help": async (_, ctx) => ctx.addSystemMessage(HELP_TEXT),

  "/models": async (_, ctx) => {
    if (!ctx.config) return;
    const lines = ctx.config.models.map((m) => {
      const active = m.name === ctx.config!.activeModel ? " *" : "  ";
      const loaded = m.loaded ? "loaded" : "      ";
      const tools = m.toolsEnabled ? "tools" : "     ";
      return `${active} ${m.name.padEnd(16)} ${loaded}  ${tools}  ${m.role}`;
    });
    ctx.addSystemMessage("```\n" + lines.join("\n") + "\n```");
  },

  "/modes": async (_, ctx) =>
    ctx.addSystemMessage(
      "**Routing modes:** manual (active model only), oracle (keyword route), " +
      "switchhook (plan vs act), broadcast (fan out to multiple models)",
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
    if (key in DEFAULT_SETTINGS) {
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
    const rows = Object.entries(ctx.settings).map(
      ([k, v]) => `| ${k} | ${(v as boolean) ? "on" : "off"} |`,
    );
    ctx.addSystemMessage(
      "**UI Settings** — use `/settings <key> on|off` or open the picker with `/settings`\n\n" +
      "| Setting | Value |\n|---------|-------|\n" +
      rows.join("\n") +
      "\n\nUse `/settings reset` to restore defaults.",
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

  "/backends": (args, ctx) =>
    runCmd("/backends", args, ctx, (result) =>
      ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```"),
    ),

  "/backend-status": (args, ctx) =>
    runCmd("/backend-status", args, ctx, (result) =>
      ctx.addSystemMessage("```json\n" + JSON.stringify(result, null, 2) + "\n```"),
    ),

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
        const lines = Object.entries(r).map(([k, v]) => `  ${k}: ${v}`).join("\n");
        ctx.addSystemMessage("```\n" + lines + "\n```");
      }
    }),

  "/reset": (args, ctx) =>
    runCmd("/reset", args, ctx, () => {
      ctx.addSystemMessage(
        `History cleared for ${args[0] || ctx.config?.activeModel || "current model"}.`,
      );
    }),

  "/tools": (args, ctx) => {
    const enabled = args[0]?.toLowerCase() === "on";
    return runCmd("/tools", args, ctx, () => {
      ctx.updateConfig({ toolsEnabled: enabled });
      ctx.addSystemMessage(`Tools ${enabled ? "enabled" : "disabled"}.`);
    });
  },

  "/servers": async (_, ctx) => {
    if (!ctx.config) return;
    if (ctx.config.servers.length > 0) {
      ctx.addSystemMessage(
        `**Servers:** ${ctx.config.servers.join(", ")}\n**Tools:** ${ctx.config.toolCount}` +
        (ctx.config.warnings.length > 0
          ? `\n**Warnings:** ${ctx.config.warnings.join("; ")}`
          : ""),
      );
    } else {
      ctx.addSystemMessage(
        ctx.config.warnings.length > 0
          ? `No tool servers connected.\n\n**Warnings:** ${ctx.config.warnings.join("; ")}`
          : "No tool servers connected.",
      );
    }
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
      const r = result as { loaded?: string; lines?: number; chars?: number } | null;
      if (r?.loaded) {
        ctx.updateConfig({ focusFile: r.loaded });
        ctx.addSystemMessage(
          `Loaded **${r.loaded}** (${r.lines} lines, ${r.chars} chars) into system prompt.\n` +
          `This context is now KV-cached — all subsequent turns benefit from it.`,
        );
      }
    });
  },

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

      let out = "**Session Statistics**\n\n| Metric | Value |\n|--------|-------|\n";
      out += `| Messages | ${r.messages} |\n`;
      out += `| Tool calls | ${toolCalls} |\n`;
      out += `| Prompt tokens | ${fmtTok(pt)} |\n`;
      out += `| Completion tokens | ${fmtTok(ct)} |\n`;
      out += `| **Total tokens** | **${fmtTok(total)}** |\n`;
      if (engines > 0) out += `| Active engines | ${engines} |\n`;
      if (modelsUsed.length > 0) out += `| Models used | ${modelsUsed.join(", ")} |\n`;
      out += `| Session | \`${r.session || "none"}\` |`;
      ctx.addSystemMessage(out);
    }),

  "/save": (args, ctx) =>
    runCmd("/save", args, ctx, (result) => {
      const r = result as { path?: string; messages?: number } | null;
      if (r?.path) {
        const short = String(r.path).replace(/^\/Users\/[^/]+/, "~");
        ctx.addSystemMessage(`Session auto-saving to:\n\`${short}\`\nMessages: ${r.messages}`);
      } else {
        ctx.addSystemMessage("No active session.");
      }
    }),

  "/sessions": (args, ctx) =>
    runCmd("/sessions", args, ctx, (result) => {
      const r = result as { sessions?: Array<Record<string, unknown>> } | null;
      const raw = r?.sessions ?? [];
      if (raw.length === 0) {
        ctx.addSystemMessage("No saved sessions.");
        return;
      }
      const sessions: SessionInfo[] = raw.map((s) => ({
        name: String(s.name ?? ""),
        started: String(s.started ?? ""),
        activeModel: String(s.active_model ?? "?"),
        models: Array.isArray(s.models) ? (s.models as string[]) : [],
        messages: typeof s.messages === "number" ? s.messages : 0,
        mode: String(s.mode ?? "manual"),
      }));
      ctx.openSessionPicker(sessions);
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
        const sessions: SessionInfo[] = raw.map((s) => ({
          name: String(s.name ?? ""),
          started: String(s.started ?? ""),
          activeModel: String(s.active_model ?? "?"),
          models: Array.isArray(s.models) ? (s.models as string[]) : [],
          messages: typeof s.messages === "number" ? s.messages : 0,
          mode: String(s.mode ?? "manual"),
        }));
        ctx.openSessionPicker(sessions);
      });
    }
    return runCmd("/resume", args, ctx, (result) => {
      const r = result as { resumed?: string; models?: string[]; messages_restored?: number } | null;
      if (r?.resumed) {
        ctx.addSystemMessage(
          `Resumed **${r.resumed}** — ${r.messages_restored} messages restored`,
        );
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
