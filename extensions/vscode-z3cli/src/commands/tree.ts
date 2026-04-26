import * as vscode from "vscode";
import type { Z3cliClient } from "../ipc/client.js";
import type { ReadyParams } from "../ipc/protocol.js";
import { COMMAND_GROUPS } from "./catalog.js";

interface TreeNode {
  label: string;
  description?: string;
  tooltip?: string;
  contextValue?: string;
  iconId?: string;
  command?: vscode.Command;
  children?: TreeNode[];
  collapsibleState?: vscode.TreeItemCollapsibleState;
}

function toItem(node: TreeNode): vscode.TreeItem {
  const item = new vscode.TreeItem(
    node.label,
    node.collapsibleState ?? (node.children?.length
      ? vscode.TreeItemCollapsibleState.Collapsed
      : vscode.TreeItemCollapsibleState.None),
  );
  if (node.description) item.description = node.description;
  if (node.tooltip) item.tooltip = node.tooltip;
  if (node.contextValue) item.contextValue = node.contextValue;
  if (node.iconId) item.iconPath = new vscode.ThemeIcon(node.iconId);
  if (node.command) item.command = node.command;
  return item;
}

export class CommandsTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private readonly emitter = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  private nodes: TreeNode[] = [];

  constructor() {
    this.nodes = COMMAND_GROUPS.map((group) => ({
      label: `${group.symbol} ${group.title}`,
      contextValue: "z3cli.group",
      iconId: groupIcon(group.key),
      collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
      children: group.entries.map((entry) => ({
        label: entry.paletteLabel ?? entry.name,
        description: entry.args || undefined,
        tooltip: entry.description,
        contextValue: "z3cli.commandLeaf",
        iconId: "play",
        command: {
          command: "z3cli.run.slash",
          title: entry.description,
          arguments: [entry],
        },
      })),
    }));
  }

  refresh(): void {
    this.emitter.fire(undefined);
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    return toItem(node);
  }

  getChildren(node?: TreeNode): TreeNode[] {
    if (!node) return this.nodes;
    return node.children ?? [];
  }
}

export class RoutesTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private readonly emitter = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  constructor(private client: Z3cliClient) {
    this.client.on("ready", () => this.refresh());
    this.client.on("done", () => this.refresh());
  }

  refresh(): void {
    this.emitter.fire(undefined);
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    return toItem(node);
  }

  getChildren(node?: TreeNode): TreeNode[] {
    if (node?.children) return node.children;
    if (node) return [];
    return this.buildRoot();
  }

  private buildRoot(): TreeNode[] {
    const ready = this.client.getReady();
    if (!ready) {
      return [{
        label: "Waiting for backend…",
        iconId: "loading~spin",
      }];
    }
    return [
      summary(ready),
      models(ready),
    ];
  }
}

function summary(ready: ReadyParams): TreeNode {
  return {
    label: "Active",
    collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
    iconId: "milestone",
    children: [
      {
        label: "Backend",
        description: ready.backend,
        iconId: "server",
      },
      {
        label: "Model",
        description: ready.active_model,
        iconId: "circuit-board",
        command: {
          command: "z3cli.model.pick",
          title: "Switch model",
        },
      },
      {
        label: "Mode",
        description: ready.mode,
        iconId: "settings",
        command: {
          command: "z3cli.mode.pick",
          title: "Switch mode",
        },
      },
      {
        label: "Workspace",
        description: ready.workspace,
        iconId: "folder",
        command: {
          command: "z3cli.workspace.set",
          title: "Set workspace",
        },
      },
    ],
  };
}

function models(ready: ReadyParams): TreeNode {
  const items = (ready.models ?? []).map((model) => ({
    label: model.name,
    description: model.role,
    tooltip: model.description ?? model.model_id,
    iconId: model.loaded ? "check" : "dash",
    command: {
      command: "z3cli.model.switch",
      title: `Switch to ${model.name}`,
      arguments: [model.name],
    },
  } satisfies TreeNode));
  return {
    label: "Models",
    collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
    iconId: "list-tree",
    children: items.length ? items : [{ label: "No models reported", iconId: "warning" }],
  };
}

function groupIcon(key: string): string {
  switch (key) {
    case "quest": return "compass";
    case "models": return "circuit-board";
    case "tools": return "tools";
    case "session": return "history";
    default: return "list-unordered";
  }
}
