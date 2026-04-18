import type { SessionInfo } from "../commands/index.js";
import type { AttachmentMeta, ConstructRef } from "../ipc/protocol.js";

export interface FileMention {
  start: number;
  end: number;
  query: string;
}

export interface ConstructMention {
  start: number;
  end: number;
  kind: string;
  query: string;
}

export interface ConstructCandidate extends ConstructRef {
  id: string;
  label: string;
  token: string;
  aliases: string;
  source?: string;
  detail?: string;
}

export interface ConstructSearchResult {
  matches: ConstructCandidate[];
  ambiguous: boolean;
  exactCount: number;
  totalCount: number;
}

export interface DraftConstructPreview extends ConstructRef {
  token: string;
  status: "resolved" | "suggested" | "ambiguous" | "unresolved";
  matchCount: number;
  source?: string;
  detail?: string;
}

export interface DraftFilePreview extends AttachmentMeta {
  origin: "picker" | "mention";
  status: "resolved" | "pending";
  typeLabel: string;
  snippet?: string;
}

export interface FilePreviewMeta {
  typeLabel: string;
  snippet?: string;
}

export interface PaletteEntry {
  key: string;
  label: string;
  description: string;
  command: string;
  aliases: string;
}

const SESSION_NAME_RE =
  /^(?<date>\d{4}-\d{2}-\d{2})_(?<hh>\d{2})(?<mm>\d{2})(?<ss>\d{2})(?:_(?<micros>\d+))?(?:_(?<slug>.+))?$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;
const CONSTRUCT_KIND_ALIASES: Record<string, string> = {
  door: "entrance",
  ent: "entrance",
  entity: "sprite",
  entrance: "entrance",
  item: "item",
  map: "overworld",
  message: "message",
  msg: "message",
  music: "music",
  npc: "sprite",
  obj: "object",
  object: "object",
  overworld: "overworld",
  overworld_map: "overworld",
  ow: "overworld",
  room: "room",
  song: "music",
  sprite: "sprite",
  track: "music",
};
const RESOURCE_LABEL_KIND_MAP: Record<string, string> = {
  entrance: "entrance",
  item: "item",
  music: "music",
  overworld_map: "overworld",
  room: "room",
  sprite: "sprite",
};
const SPRITE_CATALOG_SECTION_KINDS: Record<string, "sprite" | "object"> = {
  Bosses: "sprite",
  Enemies: "sprite",
  NPCs: "sprite",
  Objects: "object",
};
const FILE_TYPE_LABELS: Record<string, string> = {
  asm: "asm",
  c: "c",
  cfg: "config",
  cpp: "cpp",
  css: "css",
  h: "header",
  hpp: "header",
  html: "html",
  ini: "config",
  java: "java",
  js: "js",
  json: "json",
  jsx: "jsx",
  md: "md",
  org: "org",
  py: "py",
  rs: "rust",
  s: "asm",
  sh: "shell",
  toml: "toml",
  ts: "ts",
  tsx: "tsx",
  txt: "text",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
};
const FILE_PREVIEW_SNIPPET_LIMIT = 72;
const ASM_PREVIEW_OP_LIMIT = 3;
const ASM_PREVIEW_CONTROL_LIMIT = 3;
const ASM_PREVIEW_LINE_CHAR_LIMIT = 96;
const ASM_PREVIEW_OP_CHAR_LIMIT = 28;
const JSON_KEY_PREVIEW_LIMIT = 4;
const YAML_KEY_PREVIEW_LIMIT = 4;
const TOML_ENTRY_PREVIEW_LIMIT = 4;
const MARKDOWN_HEADING_PREVIEW_LIMIT = 4;
const ORG_HEADING_PREVIEW_LIMIT = 4;
const DOC_METADATA_PREVIEW_LIMIT = 4;
const DOC_PREVIEW_LINE_LIMIT = 3;
const ORG_TAG_PREVIEW_LIMIT = 4;
const FRONTMATTER_META_PRIORITY = [
  "status",
  "tags",
  "updated",
  "date",
  "draft",
  "owner",
  "author",
  "project",
  "workspace",
  "category",
  "series",
  "slug",
] as const;
const ORG_TODO_KEYWORDS = new Set([
  "TODO",
  "DONE",
  "NEXT",
  "WAITING",
  "BLOCKED",
  "CANCELLED",
  "FIXME",
  "NOTE",
]);
const ASM_DIRECTIVE_TOKENS = new Set([
  "arch",
  "assert",
  "base",
  "bank",
  "cleartable",
  "db",
  "dl",
  "dw",
  "else",
  "elseif",
  "endmacro",
  "endif",
  "endnamespace",
  "endwhile",
  "fill",
  "hirom",
  "if",
  "incbin",
  "incsrc",
  "lorom",
  "macro",
  "namespace",
  "org",
  "pad",
  "padbyte",
  "print",
  "pullpc",
  "pushpc",
  "sa1rom",
  "snesheader",
  "table",
  "warnpc",
  "while",
]);

interface AsmWidthState {
  accumulator: 8 | 16 | null;
  index: 8 | 16 | null;
}

function normalizeConstructKind(kind: string): string | null {
  return CONSTRUCT_KIND_ALIASES[kind.trim().toLowerCase()] ?? null;
}

function normalizeConstructQuery(query: string): string {
  return query.trim().replace(/[.,:;!?)}\]]+$/, "");
}

function normalizeConstructKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function parseConstructInt(value: string): number | null {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (/^0x[0-9a-f]+$/.test(normalized)) return Number.parseInt(normalized, 16);
  if (/^\$[0-9a-f]+$/.test(normalized)) return Number.parseInt(normalized.slice(1), 16);
  if (/^\d+$/.test(normalized)) return Number.parseInt(normalized, 10);
  return null;
}

function constructSlug(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function cleanMarkdownCell(value: string): string {
  return value
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`/g, "")
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function parseMarkdownTableRow(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || trimmed.split("|").length < 3) return [];
  return trimmed.slice(1, -1).split("|").map((cell) => cleanMarkdownCell(cell));
}

function normalizeTableHeader(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function mergeDistinct(parts: Array<string | undefined>, separator: string): string {
  const seen = new Set<string>();
  const merged: string[] = [];
  for (const rawPart of parts) {
    const part = (rawPart ?? "").trim();
    if (!part || seen.has(part)) continue;
    seen.add(part);
    merged.push(part);
  }
  return merged.join(separator);
}

function fileExtension(filePath: string): string {
  const base = filePath.split("/").pop()?.toLowerCase() ?? filePath.toLowerCase();
  const dotIndex = base.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === base.length - 1) {
    return "";
  }
  return base.slice(dotIndex + 1);
}

function fileExtensionLabel(filePath: string): string {
  const extension = fileExtension(filePath);
  if (!extension) {
    return "file";
  }
  return FILE_TYPE_LABELS[extension] ?? extension.slice(0, 8);
}

function normalizeSnippetLine(line: string): string {
  return line.replace(/\t/g, " ").replace(/\s+/g, " ").trim();
}

function truncateSnippetLine(line: string, limit: number = FILE_PREVIEW_SNIPPET_LIMIT): string {
  if (line.length <= limit) return line;
  return `${line.slice(0, limit - 3).trimEnd()}...`;
}

function summarizePreviewList(prefix: string, values: string[], limit: number): string | undefined {
  const unique = [...new Set(values.map((value) => value.trim()).filter(Boolean))];
  if (unique.length === 0) return undefined;
  const visible = unique.slice(0, limit).join(", ");
  const suffix = unique.length > limit ? ` +${unique.length - limit}` : "";
  return truncateSnippetLine(`${prefix}: ${visible}${suffix}`);
}

function summarizePreviewPairs(prefix: string, values: string[], limit: number, charLimit: number = FILE_PREVIEW_SNIPPET_LIMIT): string | undefined {
  const unique = [...new Set(values.map((value) => value.trim()).filter(Boolean))];
  if (unique.length === 0) return undefined;
  const visible = unique.slice(0, limit).join(" · ");
  const suffix = unique.length > limit ? ` +${unique.length - limit}` : "";
  return truncateSnippetLine(`${prefix}: ${visible}${suffix}`, charLimit);
}

function compactPreviewLines(lines: Array<string | undefined>, limit: number = DOC_PREVIEW_LINE_LIMIT): string | undefined {
  const compacted = lines.map((line) => line?.trim()).filter((line): line is string => Boolean(line));
  if (compacted.length === 0) return undefined;
  return compacted.slice(0, limit).join("\n");
}

function sanitizeFileSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const line = text
    .split("\n")
    .map(normalizeSnippetLine)
    .find(Boolean);
  if (!line) return undefined;
  return truncateSnippetLine(line);
}

function stripAsmInlineComment(line: string): string {
  const semicolonIndex = line.indexOf(";");
  const trimmed = semicolonIndex >= 0 ? line.slice(0, semicolonIndex) : line;
  return trimmed.trim();
}

function extractAsmToken(line: string): string {
  return line.split(/\s+/, 1)[0] ?? "";
}

function normalizeAsmToken(token: string): string {
  return token.toLowerCase();
}

function extractAsmLabel(line: string): { label?: string; remainder: string } {
  const match = line.match(/^([A-Za-z_@?.+\-][A-Za-z0-9_@?.+\-!$#]*):\s*(.*)$/);
  if (!match) {
    return { remainder: line };
  }
  return {
    label: match[1],
    remainder: match[2] ?? "",
  };
}

function parseAsmImmediateValue(line: string): number | null {
  const match = line.match(/#(?:\$([0-9a-f]+)|%([01]+)|(\d+))/i);
  if (match?.[1]) {
    return Number.parseInt(match[1], 16);
  }
  if (match?.[2]) {
    return Number.parseInt(match[2], 2);
  }
  if (match?.[3]) {
    return Number.parseInt(match[3], 10);
  }
  return null;
}

function parseAsmWidthState(line: string): { state: Partial<AsmWidthState>; display: string } | null {
  const token = extractAsmToken(line);
  const normalizedToken = normalizeAsmToken(token);
  const compactToken = normalizedToken.replace(/[()%]/g, "").replace(/^%/, "").replace(/^\./, "");
  if (compactToken === "a8") return { state: { accumulator: 8 }, display: normalizeSnippetLine(line) };
  if (compactToken === "a16") return { state: { accumulator: 16 }, display: normalizeSnippetLine(line) };
  if (["i8", "x8", "xy8"].includes(compactToken)) return { state: { index: 8 }, display: normalizeSnippetLine(line) };
  if (["i16", "x16", "xy16"].includes(compactToken)) return { state: { index: 16 }, display: normalizeSnippetLine(line) };
  if (["ai8", "axy8", "mx8"].includes(compactToken)) {
    return { state: { accumulator: 8, index: 8 }, display: normalizeSnippetLine(line) };
  }
  if (["ai16", "axy16", "mx16"].includes(compactToken)) {
    return { state: { accumulator: 16, index: 16 }, display: normalizeSnippetLine(line) };
  }
  if (compactToken === "longa") {
    if (/\bon\b/i.test(line)) return { state: { accumulator: 16 }, display: normalizeSnippetLine(line) };
    if (/\boff\b/i.test(line)) return { state: { accumulator: 8 }, display: normalizeSnippetLine(line) };
  }
  if (compactToken === "longi") {
    if (/\bon\b/i.test(line)) return { state: { index: 16 }, display: normalizeSnippetLine(line) };
    if (/\boff\b/i.test(line)) return { state: { index: 8 }, display: normalizeSnippetLine(line) };
  }
  const mnemonic = compactToken.replace(/\.[a-z]+$/i, "");
  if (mnemonic !== "rep" && mnemonic !== "sep") {
    return null;
  }
  const immediate = parseAsmImmediateValue(line);
  if (immediate === null) {
    return null;
  }
  const state: Partial<AsmWidthState> = {};
  if (immediate & 0x20) {
    state.accumulator = mnemonic === "sep" ? 8 : 16;
  }
  if (immediate & 0x10) {
    state.index = mnemonic === "sep" ? 8 : 16;
  }
  if (state.accumulator === undefined && state.index === undefined) {
    return null;
  }
  return { state, display: normalizeSnippetLine(line) };
}

function updateAsmWidthState(current: AsmWidthState, next: Partial<AsmWidthState>): AsmWidthState {
  return {
    accumulator: next.accumulator ?? current.accumulator,
    index: next.index ?? current.index,
  };
}

function formatAsmWidthState(state: AsmWidthState): string {
  const parts: string[] = [];
  if (state.accumulator !== null) {
    parts.push(`A${state.accumulator}`);
  }
  if (state.index !== null) {
    parts.push(`X${state.index}`);
  }
  return parts.join(" ");
}

function isAsmDirectiveLine(line: string): boolean {
  const token = extractAsmToken(line);
  if (!token) return false;
  if (token.startsWith(".") || token.startsWith("!")) return true;
  return ASM_DIRECTIVE_TOKENS.has(normalizeAsmToken(token));
}

function summarizeAsmOperation(line: string): string {
  return truncateSnippetLine(normalizeSnippetLine(line), ASM_PREVIEW_OP_CHAR_LIMIT);
}

function buildAsmSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const fallbackLines: string[] = [];
  const operations: string[] = [];
  const controls: string[] = [];
  let widthState: AsmWidthState = { accumulator: null, index: null };
  let entryLabel = "";

  for (const rawLine of text.split(/\r?\n/)) {
    const stripped = stripAsmInlineComment(rawLine);
    if (!stripped || /^(\/\/|\*)/.test(stripped)) {
      continue;
    }
    const normalizedLine = normalizeSnippetLine(stripped);
    fallbackLines.push(normalizedLine);
    if (operations.length >= ASM_PREVIEW_OP_LIMIT) {
      break;
    }

    const { label, remainder } = extractAsmLabel(normalizedLine);
    if (label && !entryLabel) {
      entryLabel = label;
    }
    const body = normalizeSnippetLine(remainder);
    if (!body) {
      continue;
    }

    const widthUpdate = parseAsmWidthState(body);
    if (widthUpdate) {
      widthState = updateAsmWidthState(widthState, widthUpdate.state);
      if (controls.length < ASM_PREVIEW_CONTROL_LIMIT) {
        controls.push(widthUpdate.display);
      }
      continue;
    }
    if (isAsmDirectiveLine(body)) {
      continue;
    }
    operations.push(body);
  }

  if (!entryLabel && controls.length === 0 && operations.length === 0) {
    const lines = fallbackLines;
    if (lines.length === 0) {
      return sanitizeFileSnippet(text);
    }
    return lines
      .slice(0, 2)
      .map((line) => truncateSnippetLine(line, 56))
      .join("\n");
  }

  const previewLines: string[] = [];
  if (entryLabel) {
    previewLines.push(truncateSnippetLine(`entry: ${entryLabel}`, 56));
  }
  const widthLabel = formatAsmWidthState(widthState);
  if (widthLabel) {
    const via = controls.length > 0 ? ` via ${controls.join(" -> ")}` : "";
    previewLines.push(truncateSnippetLine(`65816: ${widthLabel}${via}`, ASM_PREVIEW_LINE_CHAR_LIMIT));
  }
  if (operations.length > 0) {
    previewLines.push(
      truncateSnippetLine(
        `ops: ${operations.map((line) => summarizeAsmOperation(line)).join(" · ")}`,
        ASM_PREVIEW_LINE_CHAR_LIMIT,
      ),
    );
  }
  const preview = compactPreviewLines(previewLines);
  if (preview) {
    return preview;
  }

  const lines = fallbackLines;
  if (lines.length === 0) {
    return sanitizeFileSnippet(text);
  }
  return lines
    .slice(0, 2)
    .map((line) => truncateSnippetLine(line, 56))
    .join("\n");
}

function summarizeJsonValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `array[${value.length}]`;
  }
  if (value && typeof value === "object") {
    return "object";
  }
  return JSON.stringify(value);
}

function buildJsonSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  try {
    const parsed = JSON.parse(text) as unknown;
    if (Array.isArray(parsed)) {
      if (parsed.length === 0) return "array[0]";
      const sample = parsed.slice(0, 3).map(summarizeJsonValue).join(", ");
      const suffix = parsed.length > 3 ? ` +${parsed.length - 3}` : "";
      return truncateSnippetLine(`array[${parsed.length}] ${sample}${suffix}`);
    }
    if (parsed && typeof parsed === "object") {
      const keys = Object.keys(parsed as Record<string, unknown>);
      if (keys.length === 0) return "{}";
      return summarizePreviewList("keys", keys, JSON_KEY_PREVIEW_LIMIT);
    }
    return truncateSnippetLine(`value: ${JSON.stringify(parsed)}`);
  } catch {
    return undefined;
  }
}

function buildYamlSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const keys: string[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.replace(/\t/g, "    ");
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed === "---" || trimmed === "...") continue;
    if (/^\s/.test(line)) continue;
    const match = trimmed.match(/^([A-Za-z0-9_.-]+|"(?:[^"\\]|\\.)+"|'[^']+')\s*:/);
    if (!match) continue;
    const key = match[1]?.replace(/^['"]|['"]$/g, "");
    if (key) {
      keys.push(key);
    }
  }
  return summarizePreviewList("keys", keys, YAML_KEY_PREVIEW_LIMIT);
}

function buildTomlSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const tables: string[] = [];
  const keys: string[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const trimmed = rawLine.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const arrayTableMatch = trimmed.match(/^\[\[([^\]]+)\]\]$/);
    if (arrayTableMatch?.[1]) {
      tables.push(arrayTableMatch[1].trim());
      continue;
    }
    const tableMatch = trimmed.match(/^\[([^\]]+)\]$/);
    if (tableMatch?.[1]) {
      tables.push(tableMatch[1].trim());
      continue;
    }
    if (/^\s/.test(rawLine)) continue;
    const keyMatch = trimmed.match(/^([A-Za-z0-9_.-]+)\s*=/);
    if (keyMatch?.[1]) {
      keys.push(keyMatch[1]);
    }
  }
  return summarizePreviewList(tables.length > 0 ? "tables" : "keys", tables.length > 0 ? tables : keys, TOML_ENTRY_PREVIEW_LIMIT);
}

interface MarkdownFrontmatterSummary {
  title?: string;
  metaLine?: string;
  teaser?: string;
  body: string;
}

interface OrgHeadingSummary {
  title: string;
  todo?: string;
  tags: string[];
}

function parseFrontmatterArrayValue(rawValue: string): string {
  const normalized = rawValue.trim();
  if (!normalized.startsWith("[") || !normalized.endsWith("]")) {
    return normalized.replace(/^['"]|['"]$/g, "");
  }
  return normalized
    .slice(1, -1)
    .split(",")
    .map((item) => item.trim().replace(/^['"]|['"]$/g, ""))
    .filter(Boolean)
    .join(", ");
}

function extractMarkdownFrontmatter(text: string): MarkdownFrontmatterSummary | null {
  if (!text || text.includes("\0")) return null;
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") {
    return null;
  }
  let closingIndex = -1;
  for (let index = 1; index < lines.length; index += 1) {
    const trimmed = lines[index]?.trim();
    if (trimmed === "---" || trimmed === "...") {
      closingIndex = index;
      break;
    }
  }
  if (closingIndex <= 0) {
    return null;
  }

  const entries = new Map<string, string>();
  let activeListKey = "";
  for (const rawLine of lines.slice(1, closingIndex)) {
    const line = rawLine.replace(/\t/g, "    ");
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const listMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (activeListKey && listMatch?.[1]) {
      const existing = entries.get(activeListKey) ?? "";
      const nextValue = listMatch[1].trim().replace(/^['"]|['"]$/g, "");
      entries.set(activeListKey, existing ? `${existing}, ${nextValue}` : nextValue);
      continue;
    }
    if (/^\s/.test(line)) {
      activeListKey = "";
      continue;
    }
    const match = trimmed.match(/^([A-Za-z0-9_.-]+|"(?:[^"\\]|\\.)+"|'[^']+')\s*:\s*(.*)$/);
    if (!match) {
      activeListKey = "";
      continue;
    }
    const key = match[1]?.replace(/^['"]|['"]$/g, "").toLowerCase() ?? "";
    const rawValue = match[2] ?? "";
    entries.set(key, parseFrontmatterArrayValue(rawValue));
    activeListKey = rawValue.trim() ? "" : key;
  }

  const title = entries.get("title") || entries.get("name") || entries.get("slug") || undefined;
  const metaParts = FRONTMATTER_META_PRIORITY
    .map((key) => {
      const value = entries.get(key);
      return value ? `${key}=${value}` : "";
    })
    .filter(Boolean);
  const fallbackMeta = metaParts.length === 0
    ? summarizePreviewList("frontmatter", [...entries.keys()].filter((key) => key !== "title"), DOC_METADATA_PREVIEW_LIMIT)
    : undefined;
  const teaser = entries.get("summary") || entries.get("description") || entries.get("excerpt") || "";

  return {
    ...(title ? { title: cleanMarkdownCell(title) } : {}),
    ...(metaParts.length > 0
      ? { metaLine: summarizePreviewPairs("meta", metaParts, DOC_METADATA_PREVIEW_LIMIT, 96) }
      : fallbackMeta
        ? { metaLine: fallbackMeta }
        : {}),
    ...(teaser ? { teaser: truncateSnippetLine(cleanMarkdownCell(teaser), 64) } : {}),
    body: lines.slice(closingIndex + 1).join("\n"),
  };
}

function buildMarkdownSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const frontmatter = extractMarkdownFrontmatter(text);
  const bodyText = frontmatter?.body ?? text;
  const headings: string[] = [];
  const paragraphs: string[] = [];
  let inFence = false;
  for (const rawLine of bodyText.split(/\r?\n/)) {
    const trimmed = rawLine.trim();
    if (/^(```|~~~)/.test(trimmed)) {
      inFence = !inFence;
      continue;
    }
    if (inFence || !trimmed) continue;
    const headingMatch = trimmed.match(/^#{1,6}\s+(.+)$/);
    if (headingMatch?.[1]) {
      headings.push(cleanMarkdownCell(headingMatch[1]));
      continue;
    }
    if (/^[-*+]\s+/.test(trimmed)) continue;
    paragraphs.push(cleanMarkdownCell(trimmed));
  }
  const lines: string[] = [];
  const titleLine = frontmatter?.title || headings[0];
  if (titleLine) {
    lines.push(truncateSnippetLine(`doc: ${titleLine}`));
  }
  const headingSummary = summarizePreviewList(
    "sections",
    titleLine === headings[0] ? headings.slice(1) : headings,
    MARKDOWN_HEADING_PREVIEW_LIMIT,
  );
  if (frontmatter?.metaLine) {
    lines.push(frontmatter.metaLine);
  }
  if (headingSummary) {
    lines.push(headingSummary);
  }
  const teaser = frontmatter?.teaser || paragraphs.find((paragraph) => paragraph && paragraph !== titleLine);
  if (teaser) {
    lines.push(truncateSnippetLine(teaser, 64));
  }
  return compactPreviewLines(lines);
}

function parseOrgHeadingSummary(trimmed: string): OrgHeadingSummary | null {
  const headingMatch = trimmed.match(/^\*+\s+(.+)$/);
  if (!headingMatch?.[1]) {
    return null;
  }
  let body = headingMatch[1].trim();
  const tagsMatch = body.match(/\s+(:[A-Za-z0-9_@#%:-]+:)$|^(:[A-Za-z0-9_@#%:-]+:)$/);
  let tags: string[] = [];
  if (tagsMatch?.[1]) {
    tags = tagsMatch[1].split(":").filter(Boolean);
    body = body.slice(0, body.length - tagsMatch[1].length).trim();
  }
  const todoMatch = body.match(/^([A-Z][A-Z0-9_-]+)\b/);
  const todo = todoMatch?.[1] && ORG_TODO_KEYWORDS.has(todoMatch[1]) ? todoMatch[1] : undefined;
  if (todo) {
    body = body.slice(todo.length).trim();
  }
  body = body.replace(/^\[#.[^\]]*\]\s*/, "").trim();
  body = body.replace(/^(?:\[[^\]]+\]|\([^\)]+\))\s*/, "").trim();
  const title = cleanMarkdownCell(body);
  if (!title) {
    return null;
  }
  return { title, ...(todo ? { todo } : {}), tags };
}

function buildOrgTodoTagSummary(todoCounts: Map<string, number>, tags: string[]): string | undefined {
  const todoParts = [...todoCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, DOC_METADATA_PREVIEW_LIMIT)
    .map(([todo, count]) => `${todo}=${count}`);
  const uniqueTags = [...new Set(tags.map((tag) => tag.trim()).filter(Boolean))];
  if (todoParts.length > 0 && uniqueTags.length > 0) {
    const visibleTags = uniqueTags.slice(0, ORG_TAG_PREVIEW_LIMIT).join(", ");
    const suffix = uniqueTags.length > ORG_TAG_PREVIEW_LIMIT ? ` +${uniqueTags.length - ORG_TAG_PREVIEW_LIMIT}` : "";
    return truncateSnippetLine(`todo: ${todoParts.join(" · ")} · tags=${visibleTags}${suffix}`, 96);
  }
  if (todoParts.length > 0) {
    return summarizePreviewPairs("todo", todoParts, DOC_METADATA_PREVIEW_LIMIT, 96);
  }
  return summarizePreviewList("tags", uniqueTags, ORG_TAG_PREVIEW_LIMIT);
}

function buildOrgSnippet(text: string): string | undefined {
  if (!text || text.includes("\0")) return undefined;
  const headings: string[] = [];
  const paragraphs: string[] = [];
  const propertyEntries: string[] = [];
  const todoCounts = new Map<string, number>();
  const tagValues: string[] = [];
  let title = "";
  let inBlock = false;
  let inProperties = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const trimmed = rawLine.trim();
    if (!trimmed) continue;
    const lower = trimmed.toLowerCase();
    if (lower.startsWith("#+begin_")) {
      inBlock = true;
      continue;
    }
    if (lower.startsWith("#+end_")) {
      inBlock = false;
      continue;
    }
    if (inBlock) continue;
    if (lower === ":properties:") {
      inProperties = true;
      continue;
    }
    if (lower === ":end:" && inProperties) {
      inProperties = false;
      continue;
    }
    if (lower.startsWith("#+title:")) {
      title = cleanMarkdownCell(trimmed.slice(8));
      continue;
    }
    if (inProperties) {
      const propertyMatch = trimmed.match(/^:([^:]+):\s*(.*)$/);
      if (propertyMatch?.[1]) {
        const key = propertyMatch[1].trim().toUpperCase();
        const value = cleanMarkdownCell(propertyMatch[2] ?? "");
        propertyEntries.push(value ? `${key}=${truncateSnippetLine(value, 24)}` : key);
      }
      continue;
    }
    if (trimmed.startsWith("#+")) continue;
    const headingSummary = parseOrgHeadingSummary(trimmed);
    if (headingSummary) {
      headings.push(headingSummary.title);
      if (headingSummary.todo) {
        todoCounts.set(headingSummary.todo, (todoCounts.get(headingSummary.todo) ?? 0) + 1);
      }
      tagValues.push(...headingSummary.tags);
      continue;
    }
    if (/^[-+]\s+/.test(trimmed)) continue;
    paragraphs.push(cleanMarkdownCell(trimmed));
  }
  const lines: string[] = [];
  const titleLine = title || headings[0];
  if (titleLine) {
    lines.push(truncateSnippetLine(`doc: ${titleLine}`));
  }
  const propertySummary = summarizePreviewPairs("props", propertyEntries, DOC_METADATA_PREVIEW_LIMIT, 96);
  if (propertySummary) {
    lines.push(propertySummary);
  }
  const todoTagSummary = buildOrgTodoTagSummary(todoCounts, tagValues);
  if (todoTagSummary) {
    lines.push(todoTagSummary);
  }
  const headingSummary = summarizePreviewList(
    "headings",
    title ? headings : headings.slice(1),
    ORG_HEADING_PREVIEW_LIMIT,
  );
  if (headingSummary) {
    lines.push(headingSummary);
  }
  const teaser = paragraphs.find((paragraph) => paragraph && paragraph !== titleLine);
  if (teaser) {
    lines.push(truncateSnippetLine(teaser, 64));
  }
  return compactPreviewLines(lines);
}

function candidateMatchesRef(candidate: ConstructCandidate, ref: ConstructRef): boolean {
  if (candidate.kind !== ref.kind) return false;
  const refId = normalizeConstructKey(ref.id ?? ref.query);
  const refQuery = normalizeConstructKey(ref.query);
  const refLabel = normalizeConstructKey(ref.label ?? "");
  const candidateKeys = [candidate.id, candidate.query, candidate.label, candidate.token].map(normalizeConstructKey);
  return candidateKeys.includes(refId) || candidateKeys.includes(refQuery) || (refLabel ? candidateKeys.includes(refLabel) : false);
}

export function constructToken(ref: Pick<ConstructRef, "kind" | "query"> & { id?: string; token?: string }): string {
  if (ref.token) return ref.token;
  return `#${ref.kind}:${ref.id ?? ref.query}`;
}

export function sessionSlug(name: string): string {
  const match = name.match(SESSION_NAME_RE);
  if (!match?.groups) {
    return name;
  }
  const slug = (match.groups.slug ?? "").trim();
  if (slug) {
    return slug;
  }
  return `${match.groups.hh}:${match.groups.mm}`;
}

export function sessionDate(iso: string): string {
  if (!iso) return "?";
  try {
    const d = new Date(iso);
    const mon = MONTHS[d.getMonth()] ?? "?";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${mon} ${d.getDate()} ${hh}:${mm}`;
  } catch {
    return iso.slice(0, 10);
  }
}

export function sessionMatches(session: SessionInfo, filter: string): boolean {
  const haystack = [
    session.name,
    session.backend,
    session.activeModel,
    session.mode,
    session.workspace,
    session.preview,
    ...session.models,
  ].join(" ").toLowerCase();
  return haystack.includes(filter);
}

export function activeFileMention(text: string, cursor: number): FileMention | null {
  const before = text.slice(0, cursor);
  const match = before.match(/(?:^|\s)@([^\s@]*)$/);
  if (!match) return null;
  const query = match[1] ?? "";
  return {
    start: cursor - query.length - 1,
    end: cursor,
    query,
  };
}

export function activeConstructMention(text: string, cursor: number): ConstructMention | null {
  const before = text.slice(0, cursor);
  const match = before.match(/(?:^|\s)#([A-Za-z][A-Za-z0-9_-]*):([^\s#]*)$/);
  if (!match) return null;
  const rawKind = match[1] ?? "";
  const kind = normalizeConstructKind(rawKind);
  if (!kind) return null;
  const query = match[2] ?? "";
  return {
    start: cursor - query.length - rawKind.length - 2,
    end: cursor,
    kind,
    query,
  };
}

function subsequenceScore(text: string, query: string): number | null {
  let score = 0;
  let cursor = 0;
  for (const char of query) {
    const idx = text.indexOf(char, cursor);
    if (idx < 0) return null;
    score += idx;
    cursor = idx + 1;
  }
  return score;
}

export function scoreFileMatch(path: string, query: string): number | null {
  if (!query) return 10_000 + path.length;
  const lowerPath = path.toLowerCase();
  const lowerBase = path.split("/").pop()?.toLowerCase() ?? lowerPath;
  const lowerQuery = query.toLowerCase();

  if (lowerBase === lowerQuery) return 0;
  if (lowerPath === lowerQuery) return 1;
  if (lowerBase.startsWith(lowerQuery)) return 5 + lowerBase.length;
  if (lowerPath.startsWith(lowerQuery)) return 10 + lowerPath.length;

  const baseIndex = lowerBase.indexOf(lowerQuery);
  if (baseIndex >= 0) return 20 + baseIndex + lowerBase.length;

  const pathIndex = lowerPath.indexOf(lowerQuery);
  if (pathIndex >= 0) return 40 + pathIndex + lowerPath.length;

  const subseq = subsequenceScore(lowerPath, lowerQuery);
  if (subseq !== null) return 200 + subseq + lowerPath.length;
  return null;
}

export function filterFiles(files: string[], query: string): string[] {
  return files
    .map((path) => ({ path, score: scoreFileMatch(path, query) }))
    .filter((entry): entry is { path: string; score: number } => entry.score !== null)
    .sort((a, b) => a.score - b.score || a.path.localeCompare(b.path))
    .slice(0, 200)
    .map((entry) => entry.path);
}

export function buildConstructCandidates(payload: unknown): ConstructCandidate[] {
  if (!payload || typeof payload !== "object") return [];
  const data = payload as Record<string, unknown>;
  const candidates: ConstructCandidate[] = [];
  for (const [sectionName, rawSection] of Object.entries(data)) {
    const kind = RESOURCE_LABEL_KIND_MAP[sectionName];
    if (!kind || !rawSection || typeof rawSection !== "object") continue;
    for (const [id, rawLabel] of Object.entries(rawSection as Record<string, unknown>)) {
      if (typeof rawLabel !== "string") continue;
      const label = rawLabel.trim();
      const entryId = id.trim();
      if (!entryId || !label) continue;
      const token = `#${kind}:${entryId}`;
      candidates.push({
        kind,
        query: entryId,
        id: entryId,
        label,
        token,
        aliases: `${kind} ${entryId} ${label}`,
        source: "resource labels",
      });
    }
  }
  return candidates.sort((a, b) => a.token.localeCompare(b.token));
}

export function buildSpriteCatalogConstructCandidates(markdown: string): ConstructCandidate[] {
  const candidates: ConstructCandidate[] = [];
  let section = "";
  let kind: "sprite" | "object" | "" = "";
  let headers: string[] | null = null;

  for (const rawLine of markdown.split(/\r?\n/)) {
    const heading = rawLine.trim().match(/^##\s+(.+?)(?:\s+\(|$)/);
    if (heading) {
      section = heading[1] ?? "";
      kind = SPRITE_CATALOG_SECTION_KINDS[section] ?? "";
      headers = null;
      continue;
    }
    if (!kind) continue;
    if (!rawLine.trim().startsWith("|")) {
      if (headers && rawLine.trim()) {
        headers = null;
      }
      continue;
    }
    const cells = parseMarkdownTableRow(rawLine);
    if (cells.length === 0) continue;
    if (cells.every((cell) => !cell || /^:?-+:?$/.test(cell))) continue;
    if (!headers) {
      headers = cells.map(normalizeTableHeader);
      continue;
    }
    const row = Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""]));
    const label = cleanMarkdownCell(String(row.sprite ?? row.file ?? ""));
    if (!label) continue;
    if (kind !== "object") continue;
    const id = constructSlug(label);
    const detail = [row.location, row.status].filter(Boolean).join(" | ");
    candidates.push({
      kind,
      query: id,
      id,
      label,
      token: `#${kind}:${id}`,
      aliases: [kind, section, label, row.location, row.status, row.notes].filter(Boolean).join(" "),
      source: "sprite catalog",
      detail,
    });
  }

  return candidates.sort((a, b) => a.token.localeCompare(b.token));
}

export function mergeConstructCandidates(...groups: ConstructCandidate[][]): ConstructCandidate[] {
  const merged = new Map<string, ConstructCandidate>();
  for (const group of groups) {
    for (const candidate of group) {
      const key = `${candidate.kind}:${candidate.id}`;
      const existing = merged.get(key);
      if (!existing) {
        merged.set(key, candidate);
        continue;
      }
      merged.set(key, {
        ...existing,
        ...candidate,
        aliases: mergeDistinct([existing.aliases, candidate.aliases], " "),
        source: mergeDistinct([existing.source, candidate.source], " + ") || undefined,
        detail: mergeDistinct([existing.detail, candidate.detail], " | ") || undefined,
      });
    }
  }
  return [...merged.values()].sort((a, b) => a.token.localeCompare(b.token));
}

interface RankedConstructCandidate {
  candidate: ConstructCandidate;
  score: number;
  tier: number;
}

function rankConstructCandidate(candidate: ConstructCandidate, query: string): RankedConstructCandidate | null {
  const normalizedQuery = normalizeConstructKey(normalizeConstructQuery(query));
  if (!normalizedQuery) {
    return {
      candidate,
      score: 10_000 + candidate.token.length,
      tier: 9,
    };
  }

  const numericQuery = parseConstructInt(query);
  const numericId = parseConstructInt(candidate.id);
  if (numericQuery !== null && numericId !== null && numericQuery === numericId) {
    return { candidate, score: 0, tier: 0 };
  }

  const idKey = normalizeConstructKey(candidate.id);
  const labelKey = normalizeConstructKey(candidate.label);
  const tokenKey = normalizeConstructKey(candidate.token);
  const aliasKey = normalizeConstructKey(candidate.aliases);
  const sourceKey = normalizeConstructKey(`${candidate.source ?? ""} ${candidate.detail ?? ""}`);
  const exactKeys = [idKey, labelKey, tokenKey];
  if (exactKeys.includes(normalizedQuery)) {
    return { candidate, score: exactKeys.indexOf(normalizedQuery), tier: 0 };
  }
  if (aliasKey === normalizedQuery) {
    return { candidate, score: 4, tier: 0 };
  }

  const orderedPrefixFields = [
    { key: idKey, base: 10 },
    { key: labelKey, base: 20 },
    { key: tokenKey, base: 30 },
    { key: aliasKey, base: 40 },
  ];
  for (const field of orderedPrefixFields) {
    if (field.key.startsWith(normalizedQuery)) {
      return { candidate, score: field.base + field.key.length, tier: 1 };
    }
  }

  const orderedContainsFields = [
    { key: idKey, base: 50 },
    { key: labelKey, base: 70 },
    { key: tokenKey, base: 90 },
    { key: aliasKey, base: 110 },
    { key: sourceKey, base: 130 },
  ];
  for (const field of orderedContainsFields) {
    const index = field.key.indexOf(normalizedQuery);
    if (index >= 0) {
      return { candidate, score: field.base + index + field.key.length, tier: 2 };
    }
  }

  const orderedSubsequenceFields = [
    { key: idKey, base: 200 },
    { key: labelKey, base: 240 },
    { key: aliasKey, base: 280 },
  ];
  for (const field of orderedSubsequenceFields) {
    const subsequence = subsequenceScore(field.key, normalizedQuery);
    if (subsequence !== null) {
      return { candidate, score: field.base + subsequence + field.key.length, tier: 3 };
    }
  }

  return null;
}

function hasAmbiguousTopMatches(ranked: RankedConstructCandidate[]): boolean {
  if (ranked.length <= 1) return false;
  const [first, second] = ranked;
  if (!first || !second) return false;
  if (first.tier === 0) {
    return second.tier === 0;
  }
  if (first.tier !== second.tier) return false;
  return second.score <= first.score + 12;
}

export function searchConstructs(
  candidates: ConstructCandidate[],
  kind: string,
  query: string,
): ConstructSearchResult {
  const normalizedKind = normalizeConstructKind(kind) ?? kind;
  const normalizedQuery = normalizeConstructKey(normalizeConstructQuery(query));
  const ranked = candidates
    .filter((candidate) => candidate.kind === normalizedKind)
    .map((candidate) => rankConstructCandidate(candidate, query))
    .filter((entry): entry is RankedConstructCandidate => entry !== null)
    .sort((a, b) => a.score - b.score || a.candidate.token.localeCompare(b.candidate.token));
  const exactCount = ranked.filter((entry) => entry.tier === 0).length;
  return {
    matches: ranked.slice(0, 200).map((entry) => entry.candidate),
    ambiguous: Boolean(normalizedQuery) && (exactCount > 1 || hasAmbiguousTopMatches(ranked)),
    exactCount,
    totalCount: ranked.length,
  };
}

export function filterConstructs(
  candidates: ConstructCandidate[],
  kind: string,
  query: string,
): ConstructCandidate[] {
  return searchConstructs(candidates, kind, query).matches;
}

export function buildDraftConstructPreview(
  ref: ConstructRef,
  candidates: ConstructCandidate[],
): DraftConstructPreview {
  const token = constructToken(ref);
  const direct = candidates.find((candidate) => candidateMatchesRef(candidate, ref));
  if (direct) {
    return {
      ...ref,
      id: direct.id,
      label: direct.label,
      token,
      ...(direct.source ? { source: direct.source } : {}),
      ...(direct.detail ? { detail: direct.detail } : {}),
      status: "resolved",
      matchCount: 1,
    };
  }

  const search = searchConstructs(candidates, ref.kind, ref.id ?? ref.query);
  const topMatch = search.matches[0];
  if (!topMatch) {
    return {
      ...ref,
      token,
      status: "unresolved",
      matchCount: 0,
    };
  }

  const status = search.ambiguous
    ? "ambiguous"
    : search.exactCount === 1
      ? "resolved"
      : "suggested";
  return {
    ...ref,
    id: ref.id ?? topMatch.id,
    label: topMatch.label,
    token,
    ...(topMatch.source ? { source: topMatch.source } : {}),
    ...(topMatch.detail ? { detail: topMatch.detail } : {}),
    status,
    matchCount: search.totalCount,
  };
}

export function buildDraftConstructPreviews(
  refs: ConstructRef[],
  candidates: ConstructCandidate[],
): DraftConstructPreview[] {
  return refs.map((ref) => buildDraftConstructPreview(ref, candidates));
}

export function buildDraftFilePreviews(
  draftFiles: AttachmentMeta[],
  attachedFiles: string[],
  previewMeta: Record<string, FilePreviewMeta> = {},
): DraftFilePreview[] {
  const pickedPaths = new Set(attachedFiles);
  return draftFiles.map((file) => ({
    ...file,
    origin: pickedPaths.has(file.path) ? "picker" : "mention",
    status: file.lines > 0 || file.chars > 0 ? "resolved" : "pending",
    typeLabel: previewMeta[file.path]?.typeLabel ?? fileExtensionLabel(file.path),
    ...(previewMeta[file.path]?.snippet ? { snippet: previewMeta[file.path]!.snippet } : {}),
  }));
}

export function buildFilePreviewMeta(filePath: string, content: string): FilePreviewMeta {
  const extension = fileExtension(filePath);
  const snippet = extension === "json"
    ? buildJsonSnippet(content) ?? sanitizeFileSnippet(content)
    : extension === "asm" || extension === "s"
      ? buildAsmSnippet(content) ?? sanitizeFileSnippet(content)
      : extension === "yaml" || extension === "yml"
        ? buildYamlSnippet(content) ?? sanitizeFileSnippet(content)
        : extension === "toml"
          ? buildTomlSnippet(content) ?? sanitizeFileSnippet(content)
          : extension === "md"
            ? buildMarkdownSnippet(content) ?? sanitizeFileSnippet(content)
            : extension === "org"
              ? buildOrgSnippet(content) ?? sanitizeFileSnippet(content)
      : sanitizeFileSnippet(content);
  return {
    typeLabel: fileExtensionLabel(filePath),
    ...(snippet ? { snippet } : {}),
  };
}

export function filterPalette(entries: PaletteEntry[], query: string): PaletteEntry[] {
  if (!query) return entries.slice(0, 200);
  const lowerQuery = query.toLowerCase();
  return entries
    .map((entry) => {
      const haystack = `${entry.label} ${entry.description} ${entry.aliases}`.toLowerCase();
      const score = scoreFileMatch(haystack, lowerQuery);
      return score === null ? null : { entry, score };
    })
    .filter((item): item is { entry: PaletteEntry; score: number } => item !== null)
    .sort((a, b) => a.score - b.score || a.entry.label.localeCompare(b.entry.label))
    .slice(0, 200)
    .map((item) => item.entry);
}

export function extractMentionedFiles(text: string, files: string[]): string[] {
  const fileSet = new Set(files);
  const mentioned: string[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(/(?<!\S)@([^\s@]+)/g)) {
    const raw = (match[1] ?? "").replace(/[.,:;!?)}\]]+$/, "");
    if (!raw || !fileSet.has(raw) || seen.has(raw)) continue;
    seen.add(raw);
    mentioned.push(raw);
  }
  return mentioned;
}

export function extractMentionedConstructRefs(text: string): ConstructRef[] {
  const mentioned: ConstructRef[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(/(?<!\S)#([A-Za-z][A-Za-z0-9_-]*):([^\s#]+)/g)) {
    const kind = normalizeConstructKind(match[1] ?? "");
    const query = normalizeConstructQuery(match[2] ?? "");
    if (!kind || !query) continue;
    const key = `${kind}:${normalizeConstructKey(query)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    mentioned.push({ kind, query, token: `#${kind}:${query}` });
  }
  return mentioned;
}
