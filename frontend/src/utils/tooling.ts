import { readFile } from "node:fs/promises";
import path from "node:path";

export interface ToolPreviewLine {
  kind: "add" | "remove" | "meta" | "context";
  text: string;
}

export interface ToolPreview {
  isWrite: boolean;
  summary: string;
  targetPath?: string;
  lines: ToolPreviewLine[];
  omitted: number;
}

const WRITE_PATTERNS = [
  "write",
  "edit",
  "patch",
  "apply_patch",
  "create",
  "update",
  "save",
  "delete",
  "remove",
  "set_",
];
const PATH_KEYS = ["path", "filepath", "file_path", "reference_path", "destination", "source"];
const PREVIEW_LINE_LIMIT = 24;
const RESULT_LINE_LIMIT = 20;
const RESULT_CHAR_LIMIT = 1500;

export function parseToolArguments(jsonStr: string): Record<string, unknown> | null {
  if (!jsonStr) return null;
  try {
    const value = JSON.parse(jsonStr) as unknown;
    return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function firstPathValue(args: Record<string, unknown> | null): string {
  if (!args) return "";
  for (const key of PATH_KEYS) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function summarizeText(text: string, maxChars = 72): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return "";
  if (compact.length <= maxChars) return compact;
  return `${compact.slice(0, maxChars - 3)}...`;
}

export function looksLikeWriteTool(name: string, args: Record<string, unknown> | null): boolean {
  const lower = name.toLowerCase();
  if (WRITE_PATTERNS.some((pattern) => lower.includes(pattern))) return true;
  if (!args) return false;
  return (
    typeof args.content === "string"
    || typeof args.patch_content === "string"
    || typeof args.patch === "string"
    || Array.isArray(args.edits)
  );
}

export function summarizeToolInvocation(
  name: string,
  args: Record<string, unknown> | null,
): string {
  const targetPath = firstPathValue(args);
  if (Array.isArray(args?.edits)) {
    const count = args.edits.length;
    return targetPath ? `${targetPath} · ${count} edit${count === 1 ? "" : "s"}` : `${count} edit${count === 1 ? "" : "s"}`;
  }
  if (typeof args?.cmd === "string" && args.cmd.trim()) {
    return summarizeText(args.cmd, 84);
  }
  if (typeof args?.query === "string" && args.query.trim()) {
    return targetPath ? `${targetPath} · ${summarizeText(args.query)}` : summarizeText(args.query);
  }
  if (typeof args?.content === "string") {
    const lineCount = args.content.split("\n").length;
    return targetPath ? `${targetPath} · ${lineCount} new lines` : `${lineCount} new lines`;
  }
  if (typeof args?.patch_content === "string") {
    return targetPath ? `${targetPath} · patch` : "patch";
  }
  if (typeof args?.patch === "string") {
    return targetPath ? `${targetPath} · patch` : "patch";
  }
  if (targetPath) {
    return targetPath;
  }
  return name;
}

function previewSnippet(
  text: string,
  kind: ToolPreviewLine["kind"],
): { lines: ToolPreviewLine[]; omitted: number } {
  const rows = text.replace(/\r\n/g, "\n").split("\n");
  const visible = rows.slice(0, PREVIEW_LINE_LIMIT).map((line) => ({ kind, text: line }));
  return { lines: visible, omitted: Math.max(0, rows.length - PREVIEW_LINE_LIMIT) };
}

function renderPatchPreview(patch: string): { lines: ToolPreviewLine[]; omitted: number } {
  const rows = patch.replace(/\r\n/g, "\n").split("\n");
  const visible: ToolPreviewLine[] = [];
  for (const row of rows.slice(0, PREVIEW_LINE_LIMIT)) {
    const kind: ToolPreviewLine["kind"] =
      row.startsWith("+") && !row.startsWith("+++")
        ? "add"
        : row.startsWith("-") && !row.startsWith("---")
          ? "remove"
          : "context";
    visible.push({ kind, text: row });
  }
  return { lines: visible, omitted: Math.max(0, rows.length - PREVIEW_LINE_LIMIT) };
}

function resolvePath(workspace: string, targetPath: string): string {
  if (!targetPath) return "";
  return path.isAbsolute(targetPath) ? targetPath : path.join(workspace, targetPath);
}

async function readMaybe(filePath: string): Promise<string | null> {
  if (!filePath) return null;
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

function buildEditPreview(
  targetPath: string,
  edits: Array<Record<string, unknown>>,
): ToolPreview {
  const lines: ToolPreviewLine[] = [
    { kind: "meta", text: `--- ${targetPath || "(target)"}` },
    { kind: "meta", text: `+++ ${targetPath || "(target)"}` },
  ];
  let omitted = 0;

  edits.slice(0, 3).forEach((edit, index) => {
    lines.push({ kind: "meta", text: `@@ edit ${index + 1} @@` });
    if (typeof edit.oldText === "string") {
      const oldPreview = previewSnippet(edit.oldText, "remove");
      lines.push(...oldPreview.lines);
      omitted += oldPreview.omitted;
    }
    if (typeof edit.newText === "string") {
      const newPreview = previewSnippet(edit.newText, "add");
      lines.push(...newPreview.lines);
      omitted += newPreview.omitted;
    }
  });

  if (edits.length > 3) {
    omitted += edits.length - 3;
  }

  return {
    isWrite: true,
    summary: summarizeToolInvocation("edit", { path: targetPath, edits }),
    targetPath: targetPath || undefined,
    lines: lines.slice(0, PREVIEW_LINE_LIMIT),
    omitted,
  };
}

function buildWholeFilePreview(
  targetPath: string,
  previous: string | null,
  next: string,
): ToolPreview {
  const lines: ToolPreviewLine[] = [
    { kind: "meta", text: `--- ${previous === null ? "/dev/null" : targetPath || "(current)"}` },
    { kind: "meta", text: `+++ ${targetPath || "(proposed)"}` },
  ];

  const oldPreview = previous ? previewSnippet(previous, "remove") : { lines: [] as ToolPreviewLine[], omitted: 0 };
  const newPreview = previewSnippet(next, "add");
  lines.push(...oldPreview.lines, ...newPreview.lines);

  return {
    isWrite: true,
    summary: summarizeToolInvocation("write", { path: targetPath, content: next }),
    targetPath: targetPath || undefined,
    lines: lines.slice(0, PREVIEW_LINE_LIMIT),
    omitted: oldPreview.omitted + newPreview.omitted,
  };
}

export async function buildToolPreview(
  name: string,
  rawArgs: string,
  workspace: string,
): Promise<ToolPreview | null> {
  const args = parseToolArguments(rawArgs);
  const summary = summarizeToolInvocation(name, args);
  const targetPath = firstPathValue(args);

  if (!looksLikeWriteTool(name, args)) {
    return {
      isWrite: false,
      summary,
      targetPath: targetPath || undefined,
      lines: [],
      omitted: 0,
    };
  }

  if (typeof args?.patch_content === "string" && args.patch_content.trim()) {
    const patchPreview = renderPatchPreview(args.patch_content);
    return {
      isWrite: true,
      summary,
      targetPath: targetPath || undefined,
      lines: patchPreview.lines,
      omitted: patchPreview.omitted,
    };
  }

  if (typeof args?.patch === "string" && args.patch.trim()) {
    const patchPreview = renderPatchPreview(args.patch);
    return {
      isWrite: true,
      summary,
      targetPath: targetPath || undefined,
      lines: patchPreview.lines,
      omitted: patchPreview.omitted,
    };
  }

  if (Array.isArray(args?.edits)) {
    const edits = args.edits.filter(
      (item): item is Record<string, unknown> => Boolean(item) && typeof item === "object",
    );
    return buildEditPreview(targetPath, edits);
  }

  if (typeof args?.content === "string") {
    const previous = await readMaybe(resolvePath(workspace, targetPath));
    return buildWholeFilePreview(targetPath, previous, args.content);
  }

  if ((name.toLowerCase().includes("delete") || name.toLowerCase().includes("remove")) && targetPath) {
    const previous = await readMaybe(resolvePath(workspace, targetPath));
    if (previous !== null) {
      const removed = previewSnippet(previous, "remove");
      return {
        isWrite: true,
        summary,
        targetPath,
        lines: ([
          { kind: "meta", text: `--- ${targetPath}` },
          { kind: "meta", text: "+++ /dev/null" },
          ...removed.lines,
        ] as ToolPreviewLine[]).slice(0, PREVIEW_LINE_LIMIT),
        omitted: removed.omitted,
      };
    }
  }

  return {
    isWrite: true,
    summary,
    targetPath: targetPath || undefined,
    lines: [],
    omitted: 0,
  };
}

export function summarizeToolResult(content: string): string {
  const trimmed = content.trim();
  if (!trimmed) return "no output";
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  const first = summarizeText(lines[0] ?? "", 84);
  if (lines.length <= 1) return first || "1 line";
  return `${lines.length} lines · ${first || "output"}`;
}

export function collapseToolResult(content: string): {
  display: string;
  totalLines: number;
  hiddenLines: number;
  truncatedByChars: boolean;
  wasCollapsed: boolean;
} {
  const normalized = content.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const totalLines = lines.length;
  if (normalized.length <= RESULT_CHAR_LIMIT && totalLines <= RESULT_LINE_LIMIT) {
    return {
      display: normalized,
      totalLines,
      hiddenLines: 0,
      truncatedByChars: false,
      wasCollapsed: false,
    };
  }
  const visibleLines: string[] = [];
  let usedChars = 0;
  let truncatedByChars = false;
  for (const line of lines) {
    if (visibleLines.length >= RESULT_LINE_LIMIT) break;
    const extraNewline = visibleLines.length > 0 ? 1 : 0;
    if (usedChars + extraNewline + line.length <= RESULT_CHAR_LIMIT) {
      visibleLines.push(line);
      usedChars += extraNewline + line.length;
      continue;
    }
    const remaining = RESULT_CHAR_LIMIT - usedChars - extraNewline;
    if (remaining > 0) {
      visibleLines.push(line.slice(0, remaining));
      usedChars += extraNewline + remaining;
    }
    truncatedByChars = true;
    break;
  }

  if (visibleLines.length === 0 && normalized.length > 0) {
    visibleLines.push(normalized.slice(0, RESULT_CHAR_LIMIT));
    truncatedByChars = normalized.length > RESULT_CHAR_LIMIT;
  }

  return {
    display: visibleLines.join("\n"),
    totalLines,
    hiddenLines: Math.max(0, totalLines - visibleLines.length),
    truncatedByChars,
    wasCollapsed: true,
  };
}
