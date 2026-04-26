import * as vscode from "vscode";

let channel: vscode.OutputChannel | null = null;

export function output(): vscode.OutputChannel {
  if (!channel) {
    channel = vscode.window.createOutputChannel("Z3CLI");
  }
  return channel;
}

export function log(message: string): void {
  output().appendLine(`[${new Date().toISOString()}] ${message}`);
}

export function logError(message: string, err: unknown): void {
  const detail = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
  log(`${message}: ${detail}`);
}
