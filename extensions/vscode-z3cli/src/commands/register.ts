import * as vscode from "vscode";
import type { Z3cliClient } from "../ipc/client.js";
import type { CommandsTreeProvider, RoutesTreeProvider } from "./tree.js";
import type { CommandCatalogEntry } from "./catalog.js";
import { logError } from "../output.js";
import { splitArgs } from "./args.js";

export { splitArgs } from "./args.js";

export interface RegisterOptions {
  routes: RoutesTreeProvider;
  commands: CommandsTreeProvider;
}

export function registerCommands(
  context: vscode.ExtensionContext,
  client: Z3cliClient,
  opts: RegisterOptions,
): void {
  const reg = (id: string, handler: (...args: unknown[]) => unknown): void => {
    context.subscriptions.push(vscode.commands.registerCommand(id, handler));
  };

  // Chat panel
  reg("z3cli.chat.open", async () => {
    await vscode.commands.executeCommand("z3cli.chat.focus");
  });
  reg("z3cli.chat.send", async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
      vscode.window.showInformationMessage("Z3CLI: select code to send first.");
      return;
    }
    const selection = editor.document.getText(editor.selection);
    const language = editor.document.languageId;
    const file = vscode.workspace.asRelativePath(editor.document.uri);
    const message = `Selection from \`${file}\` (${language}):\n\n\`\`\`${language}\n${selection}\n\`\`\`\n\nWhat does this do? Any bugs or improvements?`;
    await vscode.commands.executeCommand("z3cli.chat.focus");
    await client.chat(message);
  });
  reg("z3cli.chat.clear", async () => {
    await runSlash(client, "/reset", []);
  });

  // Routes (direct route/* RPCs, no slash dispatch)
  reg("z3cli.route.list", async () => {
    const list = await fetchRouteList(client);
    if (!list) return;
    const lines = list.routes.map((r) => `${r === list.active ? "→" : " "} ${r}`);
    vscode.window.showInformationMessage(`Routes (active: ${list.active}):\n${lines.join("\n")}`);
  });
  reg("z3cli.route.switch", async () => {
    const list = await fetchRouteList(client);
    if (!list || list.items.length === 0) {
      vscode.window.showWarningMessage("Z3CLI: no routes reported by backend.");
      return;
    }
    const choice = await vscode.window.showQuickPick(list.items, {
      placeHolder: `Pick a z3cli route (active: ${list.active})`,
      matchOnDescription: true,
    });
    if (!choice) return;
    try {
      await client.request("route/select", { route: choice.label });
    } catch (err) {
      logError("route/select", err);
      vscode.window.showErrorMessage(`Z3CLI: route/select failed: ${(err as Error).message}`);
      return;
    }
    opts.routes.refresh();
  });
  reg("z3cli.route.smoke", async () => {
    const list = await fetchRouteList(client);
    const choice = list && list.items.length
      ? await vscode.window.showQuickPick(list.items, { placeHolder: "Smoke which route?" })
      : undefined;
    try {
      const params: Record<string, unknown> = {};
      if (choice) params.route = choice.label;
      const result = await client.request<RouteProbePayload>("route/probe", params);
      const ok = result?.ok ? "ok" : "FAILED";
      const route = result?.route ?? choice?.label ?? "(active)";
      vscode.window.showInformationMessage(`Z3CLI smoke ${route}: ${ok} (${result?.durationMs ?? 0}ms)`);
    } catch (err) {
      logError("route/probe", err);
      vscode.window.showErrorMessage(`Z3CLI: route/probe failed: ${(err as Error).message}`);
    }
  });

  // Models
  reg("z3cli.model.pick", async () => {
    const ready = client.getReady();
    if (!ready) {
      vscode.window.showWarningMessage("Z3CLI: backend not ready yet.");
      return;
    }
    const items: vscode.QuickPickItem[] = (ready.models ?? [])
      .filter((m) => m.selectable !== false)
      .map((m) => ({
        label: m.name,
        description: m.role,
        detail: m.description ?? m.model_id,
        picked: m.name === ready.active_model,
      }));
    const choice = await vscode.window.showQuickPick(items, {
      placeHolder: `Active: ${ready.active_model}`,
    });
    if (!choice) return;
    await runSlash(client, "/model", [choice.label]);
    opts.routes.refresh();
  });
  reg("z3cli.model.switch", async (alias: unknown) => {
    if (typeof alias !== "string") return;
    await runSlash(client, "/model", [alias]);
    opts.routes.refresh();
  });
  reg("z3cli.model.load", async () => {
    const alias = await vscode.window.showInputBox({ prompt: "Model alias to load" });
    if (!alias) return;
    await runSlash(client, "/load", [alias]);
  });
  reg("z3cli.model.unload", async () => {
    const alias = await vscode.window.showInputBox({
      prompt: "Model alias to unload (use 'all' for all)",
    });
    if (!alias) return;
    await runSlash(client, "/unload", [alias]);
  });
  reg("z3cli.model.loaded", async () => runSlash(client, "/loaded", []));

  // Modes / specialists
  reg("z3cli.mode.pick", async () => {
    const choices = ["manual", "oracle", "orchestrator", "broadcast"].map((m) => ({ label: m }));
    const ready = client.getReady();
    const choice = await vscode.window.showQuickPick(choices, {
      placeHolder: ready ? `Active mode: ${ready.mode}` : "Pick mode",
    });
    if (!choice) return;
    await runSlash(client, "/mode", [choice.label]);
  });
  reg("z3cli.specialist.pick", async () => {
    const choices = ["din", "navi", "nayru"].map((s) => ({ label: s }));
    const choice = await vscode.window.showQuickPick(choices, { placeHolder: "Pick specialist" });
    if (!choice) return;
    await runSlash(client, "/specialist", [choice.label]);
  });

  // Workspace / ROM / focus
  reg("z3cli.workspace.set", async () => {
    const folders = vscode.workspace.workspaceFolders ?? [];
    const items = folders.map((f) => ({ label: f.name, description: f.uri.fsPath }));
    items.push({ label: "Browse…", description: "" });
    const choice = await vscode.window.showQuickPick(items, { placeHolder: "Pick workspace" });
    if (!choice) return;
    let path = choice.description;
    if (choice.label === "Browse…") {
      const picked = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectMany: false });
      path = picked?.[0]?.fsPath ?? "";
    }
    if (!path) return;
    await runSlash(client, "/workspace", [path]);
  });
  reg("z3cli.rom.set", async () => {
    const picked = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { ROM: ["sfc", "smc"] },
    });
    const path = picked?.[0]?.fsPath;
    if (!path) return;
    await runSlash(client, "/rom", [path]);
  });
  reg("z3cli.focus.set", async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showInformationMessage("Z3CLI: open a file first.");
      return;
    }
    await runSlash(client, "/focus", [editor.document.uri.fsPath]);
  });
  reg("z3cli.focus.clear", async () => runSlash(client, "/focus", ["clear"]));

  // Tools toggles
  reg("z3cli.tools.toggle", async () => {
    const ready = client.getReady();
    const next = ready?.tools_enabled ? "off" : "on";
    await runSlash(client, "/tools", [next]);
  });
  reg("z3cli.tools.toggleWrite", async () => {
    const ready = client.getReady();
    const next = ready?.tools_write ? "off" : "on";
    await runSlash(client, "/tools-write", [next]);
  });
  reg("z3cli.verifyHooks.toggle", async () => {
    const ready = client.getReady();
    const next = ready?.verify_hooks ? "off" : "on";
    await runSlash(client, "/verify-hooks", [next]);
  });

  // Session
  reg("z3cli.compact", async () => runSlash(client, "/compact", []));
  reg("z3cli.reset", async () => {
    const which = await vscode.window.showQuickPick(["this model", "all"], {
      placeHolder: "Reset history scope",
    });
    if (!which) return;
    await runSlash(client, "/reset", which === "all" ? ["all"] : []);
  });
  reg("z3cli.session.save", async () => runSlash(client, "/save", []));
  reg("z3cli.session.list", async () => runSlash(client, "/sessions", []));
  reg("z3cli.session.resume", async () => {
    const name = await vscode.window.showInputBox({ prompt: "Session name to resume" });
    if (!name) return;
    await runSlash(client, "/resume", [name]);
  });
  reg("z3cli.export.training", async () => {
    const out = await vscode.window.showInputBox({ prompt: "Output JSONL path (blank for default)" });
    await runSlash(client, "/export-training", out ? [out] : []);
  });

  // Misc
  reg("z3cli.shell.run", async () => {
    const cmd = await vscode.window.showInputBox({ prompt: "Shell command (persistent session)" });
    if (!cmd) return;
    await runSlash(client, "/shell", [cmd]);
  });
  reg("z3cli.smoke", async () => runSlash(client, "/smoke", []));
  reg("z3cli.refresh", async () => {
    opts.routes.refresh();
    opts.commands.refresh();
  });
  reg("z3cli.help", async () => runSlash(client, "/help", []));

  // FIM commands (handled inline by provider; trigger forwards to VSCode trigger)
  reg("z3cli.fim.trigger", async () => {
    await vscode.commands.executeCommand("editor.action.inlineSuggest.trigger");
  });
  reg("z3cli.fim.toggle", async () => {
    const cfg = vscode.workspace.getConfiguration("z3cli.fim");
    const next = !cfg.get<boolean>("enabled", true);
    await cfg.update("enabled", next, vscode.ConfigurationTarget.Workspace);
    vscode.window.showInformationMessage(`Z3CLI FIM ${next ? "enabled" : "disabled"} (reload window).`);
  });

  // Generic dispatch used by TreeView leaves.
  reg("z3cli.run.slash", async (entry: unknown) => {
    if (!entry || typeof entry !== "object") return;
    const command = entry as CommandCatalogEntry;
    const args = command.args
      ? await promptForArgs(command)
      : [];
    if (args === undefined) return;
    await runSlash(client, command.name, args);
  });
}

async function runSlash(client: Z3cliClient, slash: string, args: string[]): Promise<void> {
  try {
    await client.runCommand(slash, args);
  } catch (err) {
    logError(`${slash} ${args.join(" ")}`, err);
    vscode.window.showErrorMessage(`Z3CLI: ${slash} failed: ${(err as Error).message}`);
  }
}

async function promptForArgs(entry: CommandCatalogEntry): Promise<string[] | undefined> {
  const raw = await vscode.window.showInputBox({
    prompt: `${entry.name} ${entry.args}`,
    placeHolder: entry.description,
  });
  if (raw === undefined) return undefined;
  if (!raw.trim()) return [];
  return splitArgs(raw);
}

interface RouteQuickPickItem extends vscode.QuickPickItem {
  label: string;
}

interface RouteListPayload {
  activeRoute?: string;
  routes?: Array<Record<string, unknown>>;
}

interface RouteProbePayload {
  route?: string;
  ok?: boolean;
  matched?: boolean;
  durationMs?: number;
  error?: string;
}

interface RouteListSummary {
  active: string;
  routes: string[];
  items: RouteQuickPickItem[];
}

async function fetchRouteList(client: Z3cliClient): Promise<RouteListSummary | null> {
  try {
    const result = await client.request<RouteListPayload>("route/list", { includeHidden: false });
    const items: RouteQuickPickItem[] = (result?.routes ?? [])
      .filter((r) => typeof r.name === "string" && (r.name as string).length > 0)
      .map((r) => ({
        label: String(r.name),
        description: stringOrUndef(r.backend) ?? stringOrUndef(r.model),
        detail: stringOrUndef(r.displayName) ?? stringOrUndef(r.detail),
      }));
    return {
      active: String(result?.activeRoute ?? ""),
      routes: items.map((i) => i.label),
      items,
    };
  } catch (err) {
    logError("route/list", err);
    vscode.window.showErrorMessage(`Z3CLI: route/list failed: ${(err as Error).message}`);
    return null;
  }
}

function stringOrUndef(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
