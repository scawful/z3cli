import * as vscode from "vscode";
import type { Z3cliClient } from "../ipc/client.js";
import type { Z3cliConfig } from "../config.js";
import { log, logError } from "../output.js";
import { fimHotPath, HotPathError, type FimRequest } from "./hot_path.js";
import { fimColdPath, ColdPathAborted } from "./cold_path.js";
import type { ModelResolver } from "./resolver.js";

const MAX_TRIM = 16; // chars to trim if suggestion ends with input boundary

export class Z3cliInlineCompletionProvider implements vscode.InlineCompletionItemProvider {
  private debounceTimer: NodeJS.Timeout | null = null;
  private debounceCancel: (() => void) | null = null;
  private currentController: AbortController | null = null;

  constructor(
    private client: Z3cliClient,
    private readConfig: () => Z3cliConfig,
    private resolver: ModelResolver,
  ) {}

  async provideInlineCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
    context: vscode.InlineCompletionContext,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlineCompletionItem[] | vscode.InlineCompletionList | null> {
    const cfg = this.readConfig();
    if (!cfg.fim.enabled) return null;
    if (!cfg.fim.languages.includes(document.languageId)) return null;
    void context;

    this.cancelInFlight();

    const debounceMs = cfg.fim.debounceMs;
    let cancelled = false;
    await new Promise<void>((resolve) => {
      this.debounceCancel = () => {
        cancelled = true;
        resolve();
      };
      this.debounceTimer = setTimeout(() => {
        this.debounceTimer = null;
        this.debounceCancel = null;
        resolve();
      }, debounceMs);
    });
    if (cancelled || token.isCancellationRequested) return null;

    const controller = new AbortController();
    this.currentController = controller;
    const onTokenCancel = token.onCancellationRequested(() => controller.abort());

    const req = buildRequest(document, position, cfg);
    if (req.prefix.trim().length === 0) {
      onTokenCancel.dispose();
      return null;
    }

    let text = "";
    const resolved = await this.resolver.resolve(req.model, false);
    if (controller.signal.aborted) {
      onTokenCancel.dispose();
      return null;
    }
    if (resolved && resolved.apiBase) {
      try {
        const hot = await fimHotPath(req, resolved, controller.signal);
        text = hot.text;
      } catch (err) {
        if (err instanceof HotPathError && err.code === "abort") {
          onTokenCancel.dispose();
          return null;
        }
        log(`hot_path failed: ${(err as Error).message}; trying cold_path`);
      }
    } else {
      log(`resolver miss for ${req.model}; falling through to cold_path`);
    }
    if (controller.signal.aborted) {
      onTokenCancel.dispose();
      return null;
    }
    if (!text) {
      try {
        const cold = await fimColdPath(this.client, req, controller.signal);
        text = cold.text;
      } catch (rpcErr) {
        if (rpcErr instanceof ColdPathAborted) {
          onTokenCancel.dispose();
          return null;
        }
        logError("cold_path", rpcErr);
        onTokenCancel.dispose();
        return null;
      }
    }
    onTokenCancel.dispose();

    text = trimSuggestion(text, req.suffix);
    if (!text) return null;

    const item = new vscode.InlineCompletionItem(text, new vscode.Range(position, position));
    return [item];
  }

  private cancelInFlight(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    if (this.debounceCancel) {
      const cancel = this.debounceCancel;
      this.debounceCancel = null;
      cancel();
    }
    if (this.currentController) {
      this.currentController.abort();
      this.currentController = null;
    }
  }
}

function buildRequest(
  doc: vscode.TextDocument,
  pos: vscode.Position,
  cfg: Z3cliConfig,
): FimRequest {
  const offset = doc.offsetAt(pos);
  const text = doc.getText();
  const prefixStart = Math.max(0, offset - cfg.fim.contextPrefixChars);
  const suffixEnd = Math.min(text.length, offset + cfg.fim.contextSuffixChars);
  return {
    prefix: text.slice(prefixStart, offset),
    suffix: text.slice(offset, suffixEnd),
    model: cfg.fim.model,
    maxTokens: cfg.fim.maxTokens,
    temperature: cfg.fim.temperature,
    stop: cfg.fim.stopTokens,
  };
}

function trimSuggestion(suggestion: string, suffix: string): string {
  if (!suggestion) return "";
  // If the model echoed part of the suffix, drop it.
  if (suffix) {
    const head = suffix.slice(0, MAX_TRIM);
    const idx = suggestion.indexOf(head);
    if (idx > 0 && head.length >= 4) {
      return suggestion.slice(0, idx);
    }
  }
  return suggestion;
}
