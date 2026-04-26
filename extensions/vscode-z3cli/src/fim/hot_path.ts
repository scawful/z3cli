import { buildFimPrompt, fimStopTokens } from "./qwen_fim.js";
import type { ResolvedModel } from "./resolver.js";

export interface FimRequest {
  prefix: string;
  suffix: string;
  model: string;
  maxTokens: number;
  temperature: number;
  stop: string[];
}

export interface FimResult {
  text: string;
  endpoint: string;
}

export type HotPathErrorCode = "connect" | "http" | "abort" | "timeout" | "parse";

export class HotPathError extends Error {
  constructor(message: string, readonly code: HotPathErrorCode) {
    super(message);
    this.name = "HotPathError";
  }
}

const DEFAULT_TIMEOUT_MS = 4000;

interface CompletionResponse {
  choices?: Array<{
    text?: string;
    finish_reason?: string;
  }>;
}

async function postCompletion(
  apiBase: string,
  body: Record<string, unknown>,
  signal: AbortSignal,
  timeoutMs: number,
): Promise<string> {
  const url = trimSlash(apiBase) + "/completions";
  const localController = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => localController.abort();
  if (signal.aborted) {
    localController.abort();
  } else {
    signal.addEventListener("abort", onCallerAbort);
  }
  const tHandle = setTimeout(() => {
    timedOut = true;
    localController.abort();
  }, timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: localController.signal,
    });
    if (!res.ok) {
      throw new HotPathError(`HTTP ${res.status} ${res.statusText}`, "http");
    }
    const json = (await res.json()) as CompletionResponse;
    return json.choices?.[0]?.text ?? "";
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      if (timedOut) {
        throw new HotPathError(`timeout after ${timeoutMs}ms`, "timeout");
      }
      throw new HotPathError("aborted", "abort");
    }
    if (err instanceof HotPathError) throw err;
    throw new HotPathError(`${(err as Error).message}`, "connect");
  } finally {
    clearTimeout(tHandle);
    signal.removeEventListener("abort", onCallerAbort);
  }
}

function trimSlash(s: string): string {
  return s.endsWith("/") ? s.slice(0, -1) : s;
}

export async function fimHotPath(
  req: FimRequest,
  resolved: ResolvedModel,
  signal: AbortSignal,
): Promise<FimResult> {
  const prompt = buildFimPrompt(req.prefix, req.suffix, req.model);
  const stop = fimStopTokens(req.model, req.stop);
  const body = {
    model: resolved.modelId,
    prompt,
    max_tokens: req.maxTokens,
    temperature: req.temperature,
    stop,
    stream: false,
  };
  const text = await postCompletion(resolved.apiBase, body, signal, DEFAULT_TIMEOUT_MS);
  return { text, endpoint: resolved.backend };
}
