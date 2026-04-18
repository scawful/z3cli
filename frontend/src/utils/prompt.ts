import type { SessionInfo } from "../commands/index.js";
import type { ConstructRef } from "../ipc/protocol.js";

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
