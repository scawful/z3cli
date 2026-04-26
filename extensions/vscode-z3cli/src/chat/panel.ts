import * as vscode from "vscode";
import type {
  ContextCompactedParams,
  DoneParams,
  ErrorParams,
  MessageParams,
  ReadyParams,
  SubagentDoneParams,
  SubagentErrorParams,
  SubagentStartParams,
  SubagentTextParams,
  SubagentThinkingParams,
  SubagentToolCallParams,
  SubagentToolResultParams,
  TextParams,
  ThinkingParams,
  ToolCallParams,
  ToolPermissionRequestParams,
  ToolReviewRequestParams,
  ToolResultParams,
} from "../ipc/protocol.js";
import type { Z3cliClient } from "../ipc/client.js";
import { logError } from "../output.js";
import { splitArgs } from "../commands/args.js";
import { CHAT_HTML } from "./html.js";

interface ChatOutbound {
  type:
    | "ready"
    | "text"
    | "thinking"
    | "tool_call"
    | "tool_result"
    | "tool/permission_request"
    | "tool/review_request"
    | "message"
    | "done"
    | "error"
    | "context/compacted"
    | "subagent/start"
    | "subagent/text"
    | "subagent/thinking"
    | "subagent/tool_call"
    | "subagent/tool_result"
    | "subagent/done"
    | "subagent/error"
    | "reset";
  payload?: unknown;
}

interface ChatInbound {
  type: "send" | "cancel" | "command" | "modelPick" | "modePick" | "routePick" | "ready";
  message?: string;
  cmd?: string;
  args?: string[];
  alias?: string;
}

export class ChatPanelProvider implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | null = null;
  private subscriptions: vscode.Disposable[] = [];

  constructor(_context: vscode.ExtensionContext, private client: Z3cliClient) {
    this.wireClient();
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = CHAT_HTML;
    view.webview.onDidReceiveMessage((msg: ChatInbound) => this.handleInbound(msg));
    const ready = this.client.getReady();
    if (ready) this.post({ type: "ready", payload: ready });
  }

  private wireClient(): void {
    const on = <T>(event: string, fn: (params: T) => void): void => {
      this.client.on(event, fn);
      this.subscriptions.push(new vscode.Disposable(() => this.client.off(event, fn)));
    };
    on<ReadyParams>("ready", (p) => this.post({ type: "ready", payload: p }));
    on<TextParams>("text", (p) => this.post({ type: "text", payload: p }));
    on<ThinkingParams>("thinking", (p) => this.post({ type: "thinking", payload: p }));
    on<ToolCallParams>("tool_call", (p) => this.post({ type: "tool_call", payload: p }));
    on<ToolResultParams>("tool_result", (p) => this.post({ type: "tool_result", payload: p }));
    on<ToolPermissionRequestParams>("tool/permission_request", (p) => this.post({ type: "tool/permission_request", payload: p }));
    on<ToolReviewRequestParams>("tool/review_request", (p) => this.post({ type: "tool/review_request", payload: p }));
    on<MessageParams>("message", (p) => this.post({ type: "message", payload: p }));
    on<DoneParams>("done", (p) => this.post({ type: "done", payload: p }));
    on<ErrorParams>("error", (p) => this.post({ type: "error", payload: p }));
    on<ContextCompactedParams>("context/compacted", (p) => this.post({ type: "context/compacted", payload: p }));
    on<SubagentStartParams>("subagent/start", (p) => this.post({ type: "subagent/start", payload: p }));
    on<SubagentTextParams>("subagent/text", (p) => this.post({ type: "subagent/text", payload: p }));
    on<SubagentThinkingParams>("subagent/thinking", (p) => this.post({ type: "subagent/thinking", payload: p }));
    on<SubagentToolCallParams>("subagent/tool_call", (p) => this.post({ type: "subagent/tool_call", payload: p }));
    on<SubagentToolResultParams>("subagent/tool_result", (p) => this.post({ type: "subagent/tool_result", payload: p }));
    on<SubagentDoneParams>("subagent/done", (p) => this.post({ type: "subagent/done", payload: p }));
    on<SubagentErrorParams>("subagent/error", (p) => this.post({ type: "subagent/error", payload: p }));
  }

  private post(message: ChatOutbound): void {
    void this.view?.webview.postMessage(message);
  }

  private async handleInbound(msg: ChatInbound): Promise<void> {
    try {
      switch (msg.type) {
        case "send":
          if (msg.message) await this.handleSend(msg.message);
          break;
        case "cancel":
          await this.client.cancel();
          break;
        case "command":
          if (msg.cmd) await this.client.runCommand(msg.cmd, msg.args ?? []);
          break;
        case "modelPick":
          await vscode.commands.executeCommand("z3cli.model.pick");
          break;
        case "modePick":
          await vscode.commands.executeCommand("z3cli.mode.pick");
          break;
        case "routePick":
          await vscode.commands.executeCommand("z3cli.route.switch");
          break;
        case "ready": {
          const ready = this.client.getReady();
          if (ready) this.post({ type: "ready", payload: ready });
          break;
        }
      }
    } catch (err) {
      logError(`chat handleInbound ${msg.type}`, err);
      this.post({ type: "error", payload: { message: (err as Error).message } });
    }
  }

  private async handleSend(rawMessage: string): Promise<void> {
    const message = rawMessage.trim();
    if (!message) return;
    if (message.startsWith("/")) {
      const [cmd, ...args] = splitArgs(message);
      if (cmd) {
        const result = await this.client.runCommand(cmd, args);
        this.postSystem(formatCommandResult(cmd, result));
      }
      return;
    }
    await this.client.chat(message, this.editorContextParams(message));
  }

  private editorContextParams(message: string): Record<string, unknown> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.uri.scheme !== "file") return {};
    const shouldAttach = !editor.selection.isEmpty || /\b(this|current|active|selected|selection|file|buffer)\b/i.test(message);
    if (!shouldAttach) return {};
    return { attachments: [{ path: editor.document.uri.fsPath }] };
  }

  private postSystem(content: string): void {
    this.post({
      type: "message",
      payload: {
        id: `local-${Date.now()}`,
        role: "system",
        content,
        timestamp: Date.now(),
      },
    });
  }

  dispose(): void {
    for (const s of this.subscriptions) s.dispose();
  }
}

function formatCommandResult(cmd: string, result: unknown): string {
  if (result && typeof result === "object") {
    const payload = result as Record<string, unknown>;
    if (typeof payload.text === "string") return payload.text;
    if (typeof payload.message === "string") return payload.message;
    if (typeof payload.mode === "string") return `${cmd}: ${payload.mode}`;
    if (typeof payload.tools_enabled === "boolean") return `Tools enabled: ${payload.tools_enabled}`;
    if (typeof payload.tools_write === "boolean") return `Tool write access: ${payload.tools_write}`;
    if (typeof payload.verify_hooks === "boolean") return `Verification hooks: ${payload.verify_hooks}`;
    if (typeof payload.ok === "boolean") return `${cmd}: ok`;
    return `${cmd}: ${JSON.stringify(payload, null, 2)}`;
  }
  return `${cmd}: ${String(result ?? "ok")}`;
}
