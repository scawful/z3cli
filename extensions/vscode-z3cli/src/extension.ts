import * as vscode from "vscode";
import { log, logError, output } from "./output.js";
import { readConfig } from "./config.js";
import { Z3cliClient } from "./ipc/client.js";
import { StatusBar } from "./status/bar.js";
import { registerCommands } from "./commands/register.js";
import { RoutesTreeProvider, CommandsTreeProvider } from "./commands/tree.js";
import { ChatPanelProvider } from "./chat/panel.js";
import { Z3cliInlineCompletionProvider } from "./fim/provider.js";
import { ModelResolver } from "./fim/resolver.js";

let client: Z3cliClient | null = null;
let statusBar: StatusBar | null = null;
let chatPanel: ChatPanelProvider | null = null;

export function activate(context: vscode.ExtensionContext): void {
  output().show(true);
  const version = String(context.extension.packageJSON.version ?? "unknown");
  log(`activate ${context.extension.id}@${version}`);

  const cfg = readConfig();
  client = new Z3cliClient({ cfg });
  statusBar = new StatusBar(client);
  context.subscriptions.push(statusBar);

  client.on("error", (params: { message: string }) => {
    log(`backend error: ${params.message}`);
  });

  client.once("ready", (ready) => {
    log(`ready · backend=${ready.backend} model=${ready.active_model} workspace=${ready.workspace}`);
    void applyDefaultRoute(client!, cfg);
  });

  client.on("event", (evt) => {
    // Surfacing every event is too noisy; keep the channel quiet by default.
    void evt;
  });

  client.start();

  // Slice 2: slash commands + tree views.
  const routes = new RoutesTreeProvider(client);
  const commands = new CommandsTreeProvider();
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("z3cli.routes", routes),
    vscode.window.registerTreeDataProvider("z3cli.commands", commands),
  );
  registerCommands(context, client, { routes, commands });

  // Slice 3: chat panel webview.
  chatPanel = new ChatPanelProvider(context, client);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("z3cli.chat", chatPanel, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  // Slice 4: inline completion provider.
  const resolver = new ModelResolver(client);
  if (cfg.fim.enabled) {
    const provider = new Z3cliInlineCompletionProvider(client, () => readConfig(), resolver);
    const selector: vscode.DocumentSelector = cfg.fim.languages.map((language) => ({
      scheme: "file",
      language,
    }));
    context.subscriptions.push(
      vscode.languages.registerInlineCompletionItemProvider(selector, provider),
    );
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("z3cli")) {
        log("configuration changed; restart Z3CLI to apply transport changes");
      }
    }),
  );
}

export function deactivate(): void {
  log("deactivate");
  void client?.stop();
  client = null;
  statusBar = null;
  chatPanel = null;
}

async function applyDefaultRoute(c: Z3cliClient, cfg: ReturnType<typeof readConfig>): Promise<void> {
  const route = cfg.chat.defaultRoute.trim();
  if (!route) return;
  try {
    await c.request("route/select", { route });
    log(`applied default route ${route}`);
  } catch (err) {
    logError("default route", err);
  }
}
