import type { SessionInfo } from "../commands/index.js";

export interface FileMention {
  start: number;
  end: number;
  query: string;
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
