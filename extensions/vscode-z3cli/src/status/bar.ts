import * as vscode from "vscode";
import type { Z3cliClient } from "../ipc/client.js";
import type { ReadyParams } from "../ipc/protocol.js";

export class StatusBar implements vscode.Disposable {
  private items: vscode.StatusBarItem[];
  private root: vscode.StatusBarItem;
  private route: vscode.StatusBarItem;
  private cache: vscode.StatusBarItem;

  constructor(private client: Z3cliClient) {
    this.root = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.root.command = "z3cli.chat.open";
    this.root.text = "$(sparkle) z3cli starting…";
    this.root.tooltip = "Open Z3CLI chat";
    this.root.show();

    this.route = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    this.route.command = "z3cli.route.switch";
    this.route.text = "$(milestone) route —";
    this.route.tooltip = "Switch z3cli route";
    this.route.show();

    this.cache = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 98);
    this.cache.command = "z3cli.refresh";
    this.cache.text = "$(database) cache —";
    this.cache.tooltip = "Anthropic prompt-cache hit rate (cache reads / cache total)";
    this.cache.hide();

    this.items = [this.root, this.route, this.cache];

    this.client.on("ready", (params: ReadyParams) => this.applyReady(params));
    this.client.on("done", () => this.refreshFromReady());
    this.client.on("exit", () => this.markDown());
  }

  private applyReady(params: ReadyParams): void {
    const model = params.active_model || "—";
    const backend = params.backend || "?";
    this.root.text = `$(sparkle) z3cli · ${model}`;
    this.root.tooltip = `backend ${backend} · mode ${params.mode}`;

    const route = pickRouteLabel(params);
    this.route.text = `$(milestone) ${route}`;
    this.route.tooltip = `Active route — click to switch`;

    this.updateCache(params);
  }

  private refreshFromReady(): void {
    const ready = this.client.getReady();
    if (ready) this.updateCache(ready);
  }

  private updateCache(params: ReadyParams): void {
    const reads = params.cache_read_tokens ?? 0;
    const creation = params.cache_creation_tokens ?? 0;
    const denominator = reads + creation;
    if (denominator <= 0) {
      this.cache.hide();
      return;
    }
    const rate = (reads / denominator) * 100;
    this.cache.text = `$(database) cache ${rate.toFixed(0)}%`;
    this.cache.tooltip = `cache reads ${reads} / total ${denominator}`;
    this.cache.show();
  }

  private markDown(): void {
    this.root.text = "$(sparkle) z3cli offline";
    this.route.text = "$(milestone) route —";
    this.cache.hide();
  }

  dispose(): void {
    for (const it of this.items) it.dispose();
  }
}

function pickRouteLabel(params: ReadyParams): string {
  if (params.studio_node) return params.studio_node;
  if (params.llamacpp_node) return params.llamacpp_node;
  if (params.backend === "studio" && params.studio_model) return params.studio_model;
  if (params.backend === "llamacpp" && params.llamacpp_model) return params.llamacpp_model;
  return params.backend;
}
