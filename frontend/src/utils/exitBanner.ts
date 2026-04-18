export interface ExitSummary {
  model: string;
  sessionPath: string;
  messageCount: number;
  promptTokens: number;
  completionTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  durationMs: number;
}

export const CLEAR_SCREEN = "\x1b[2J\x1b[3J\x1b[H";

function basename(path: string): string {
  if (!path) return "";
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

export function resumeNameFromSessionPath(sessionPath: string): string {
  const base = basename(sessionPath);
  return base.endsWith(".jsonl") ? base.slice(0, -".jsonl".length) : base;
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  const restMin = minutes % 60;
  return `${hours}h ${restMin}m`;
}

function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function cacheHitRate(reads: number, creations: number): string {
  const total = reads + creations;
  if (total === 0) return "—";
  return `${Math.round((reads / total) * 100)}%`;
}

export function renderExitBanner(summary: ExitSummary): string {
  const name = resumeNameFromSessionPath(summary.sessionPath);
  const totalTokens = summary.promptTokens + summary.completionTokens;
  const lines: string[] = [];
  lines.push("");
  lines.push("── Session ended ──");
  lines.push(`  model     ${summary.model || "(unknown)"}`);
  lines.push(`  duration  ${formatDuration(summary.durationMs)}`);
  lines.push(`  messages  ${summary.messageCount}`);
  lines.push(
    `  tokens    ${formatTokens(totalTokens)}`
      + ` (in ${formatTokens(summary.promptTokens)}`
      + ` · out ${formatTokens(summary.completionTokens)})`,
  );
  lines.push(
    `  cache     ${cacheHitRate(summary.cacheReadTokens, summary.cacheCreationTokens)} hit`
      + ` (read ${formatTokens(summary.cacheReadTokens)}`
      + ` · write ${formatTokens(summary.cacheCreationTokens)})`,
  );
  lines.push("");
  if (name) {
    lines.push(`  Resume with:  z3cli /resume ${name}`);
  } else {
    lines.push(`  No session file was saved.`);
  }
  lines.push("");
  return lines.join("\n");
}
