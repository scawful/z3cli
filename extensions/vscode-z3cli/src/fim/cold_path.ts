import type { Z3cliClient } from "../ipc/client.js";
import type { FimRequest } from "./hot_path.js";

export interface ColdResult {
  text: string;
  finishReason?: string;
  promptTokens?: number;
  completionTokens?: number;
}

interface CompleteResponse {
  text?: string;
  finish_reason?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export class ColdPathAborted extends Error {
  constructor() {
    super("aborted");
    this.name = "ColdPathAborted";
  }
}

export async function fimColdPath(
  client: Z3cliClient,
  req: FimRequest,
  signal?: AbortSignal,
): Promise<ColdResult> {
  if (signal?.aborted) throw new ColdPathAborted();
  const params: Record<string, unknown> = {
    prefix: req.prefix,
    suffix: req.suffix,
    max_tokens: req.maxTokens,
    temperature: req.temperature,
    stop: req.stop,
  };
  if (req.model) params.model = req.model;
  const requestPromise = client.request<CompleteResponse>("complete", params, 20_000);
  const racers: Array<Promise<CompleteResponse | undefined>> = [requestPromise];
  let abortReject: ((err: Error) => void) | null = null;
  let onAbort: (() => void) | null = null;
  if (signal) {
    racers.push(
      new Promise<never>((_, reject) => {
        abortReject = reject;
        onAbort = () => {
          abortReject?.(new ColdPathAborted());
          abortReject = null;
        };
        signal.addEventListener("abort", onAbort);
      }),
    );
  }
  try {
    const result = (await Promise.race(racers)) ?? {};
    return {
      text: result.text ?? "",
      finishReason: result.finish_reason,
      promptTokens: result.prompt_tokens,
      completionTokens: result.completion_tokens,
    };
  } finally {
    if (signal && onAbort) signal.removeEventListener("abort", onAbort);
  }
}
