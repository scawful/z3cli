import * as vscode from "vscode";

export interface Z3cliConfig {
  pythonPath: string;
  module: string;
  checkoutPath: string;
  serveCommand: string[];
  extraArgs: string[];
  maxRestarts: number;
  workspace: string;
  rom: string;
  studioApiBase: string;
  llamacppApiBase: string;
  fim: {
    enabled: boolean;
    endpoint: "auto" | "studio" | "llamacpp";
    model: string;
    maxTokens: number;
    temperature: number;
    stopTokens: string[];
    debounceMs: number;
    languages: string[];
    contextPrefixChars: number;
    contextSuffixChars: number;
  };
  chat: {
    defaultMode: string;
    defaultRoute: string;
  };
}

export function readConfig(): Z3cliConfig {
  const cfg = vscode.workspace.getConfiguration("z3cli");
  const fim = cfg.get<Record<string, unknown>>("fim") ?? {};
  const chat = cfg.get<Record<string, unknown>>("chat") ?? {};
  return {
    pythonPath: cfg.get<string>("pythonPath", "python3"),
    module: cfg.get<string>("module", "z3cli"),
    checkoutPath: cfg.get<string>("checkoutPath", ""),
    serveCommand: cfg.get<string[]>("serveCommand", []),
    extraArgs: cfg.get<string[]>("extraArgs", []),
    maxRestarts: cfg.get<number>("maxRestarts", 8),
    workspace: cfg.get<string>("workspace", ""),
    rom: cfg.get<string>("rom", ""),
    studioApiBase: cfg.get<string>("studioApiBase", "http://127.0.0.1:1234/v1"),
    llamacppApiBase: cfg.get<string>("llamacppApiBase", "http://127.0.0.1:8080/v1"),
    fim: {
      enabled: (fim.enabled as boolean) ?? true,
      endpoint: ((fim.endpoint as string) ?? "auto") as "auto" | "studio" | "llamacpp",
      model: (fim.model as string) ?? "navi",
      maxTokens: (fim.maxTokens as number) ?? 96,
      temperature: (fim.temperature as number) ?? 0.1,
      stopTokens: (fim.stopTokens as string[]) ?? [
        "<|endoftext|>",
        "<|fim_pad|>",
        "<|file_separator|>",
      ],
      debounceMs: (fim.debounceMs as number) ?? 150,
      languages: (fim.languages as string[]) ?? [
        "asar",
        "65816-assembly",
        "assembly",
        "c",
        "cpp",
        "typescript",
        "javascript",
        "python",
        "markdown",
      ],
      contextPrefixChars: (fim.contextPrefixChars as number) ?? 2000,
      contextSuffixChars: (fim.contextSuffixChars as number) ?? 1000,
    },
    chat: {
      defaultMode: (chat.defaultMode as string) ?? "",
      defaultRoute: (chat.defaultRoute as string) ?? "",
    },
  };
}

export function resolveWorkspace(cfg: Z3cliConfig): string | undefined {
  if (cfg.workspace.trim()) {
    return cfg.workspace;
  }
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder?.uri.fsPath;
}
