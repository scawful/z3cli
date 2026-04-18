import type { ShowThinkingMode, ThinkingDetailMode } from "../hooks/useSettings.js";

export interface ThinkingPreview {
  text: string;
  truncated: boolean;
  overflowLabel?: string;
  lineCount: number;
}

export interface ThinkingPreviewOptions {
  mode?: "head" | "tail";
  lineLimit?: number;
  charLimit?: number;
}

export function prefixThinkingLines(text: string, prefix: string = "│ "): string {
  return text
    .split("\n")
    .map((line) => `${prefix}${line}`)
    .join("\n");
}

export function showStreamingThinking(mode: ShowThinkingMode): boolean {
  return mode !== "off";
}

export function showTranscriptThinking(mode: ShowThinkingMode): boolean {
  return mode === "transcript";
}

export function showSubagentThinking(
  mode: ShowThinkingMode,
  status: "running" | "done" | "error" | "cancelled",
): boolean {
  if (mode === "off") return false;
  if (mode === "streamed-only") return status === "running";
  return true;
}

const DEFAULT_LINE_LIMIT = 6;
const DEFAULT_CHAR_LIMIT = 480;

function normalizeHeadBoundary(value: string): string {
  const boundary = value.lastIndexOf(" ");
  if (boundary <= 0) return value.trimEnd();
  return value.slice(0, boundary).trimEnd();
}

function normalizeTailBoundary(value: string): string {
  const boundary = value.indexOf(" ");
  if (boundary < 0 || boundary >= value.length - 1) return value.trimStart();
  return value.slice(boundary + 1).trimStart();
}

export function buildThinkingPreview(
  content: string,
  options: ThinkingPreviewOptions = {},
): ThinkingPreview {
  const {
    mode = "head",
    lineLimit = DEFAULT_LINE_LIMIT,
    charLimit = DEFAULT_CHAR_LIMIT,
  } = options;
  const trimmed = content.trim();
  if (!trimmed) {
    return { text: "", truncated: false, lineCount: 0 };
  }

  const lines = trimmed.split("\n");
  const lineTruncated = lines.length > lineLimit;
  const visibleLines = lineTruncated
    ? mode === "tail"
      ? lines.slice(-lineLimit)
      : lines.slice(0, lineLimit)
    : lines;
  const joined = visibleLines.join("\n").trim();
  const charTruncated = joined.length > charLimit;
  let previewText = joined;
  if (charTruncated) {
    previewText = mode === "tail"
      ? normalizeTailBoundary(joined.slice(-charLimit))
      : normalizeHeadBoundary(joined.slice(0, charLimit));
  }

  return {
    text: previewText,
    truncated: lineTruncated || charTruncated,
    overflowLabel: lineTruncated
      ? `${lines.length - lineLimit} more lines`
      : charTruncated
        ? `${joined.length - charLimit} more chars`
        : undefined,
    lineCount: lines.length,
  };
}

export function buildThinkingDisplay(
  content: string,
  detail: ThinkingDetailMode,
  options: ThinkingPreviewOptions = {},
): ThinkingPreview {
  if (detail !== "full") {
    return buildThinkingPreview(content, options);
  }
  const trimmed = content.trim();
  if (!trimmed) {
    return { text: "", truncated: false, lineCount: 0 };
  }
  return {
    text: trimmed,
    truncated: false,
    lineCount: trimmed.split("\n").length,
  };
}
