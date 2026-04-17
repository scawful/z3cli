/**
 * Pure reducer for subagent panel state.
 *
 * Translates the stream of subagent/* IPC events into a list of
 * subagent entries for rendering. Kept free of React and Ink so it
 * can be unit-tested without the UI layer.
 */

export type SubagentStatus = "running" | "done" | "error" | "cancelled";

export interface SubagentEntry {
  id: string;
  name: string;
  model: string;
  provider: string;
  depth: number;
  parentId?: string;
  status: SubagentStatus;
  text: string;
  thinking: string;
  toolCallCount: number;
  activeTool?: { name: string; server: string };
  startedAt: number;
  finishedAt?: number;
  error?: string;
  promptTokens?: number;
  completionTokens?: number;
}

export type SubagentEvent =
  | {
      kind: "start";
      id: string;
      name: string;
      model: string;
      provider: string;
      depth?: number;
      parentId?: string;
    }
  | { kind: "text"; id: string; delta: string }
  | { kind: "thinking"; id: string; delta: string }
  | { kind: "tool_call"; id: string; name: string; server: string }
  | { kind: "tool_result"; id: string }
  | {
      kind: "done";
      id: string;
      name: string;
      model: string;
      text: string;
      promptTokens: number;
      completionTokens: number;
      toolCalls: number;
      error?: string;
      cancelled?: boolean;
    }
  | { kind: "error"; id: string; message: string };

/**
 * Apply a single subagent event to the current entry list.
 * Unknown ids on text/tool events are silently dropped.
 */
export function applySubagentEvent(
  entries: SubagentEntry[],
  event: SubagentEvent,
  now: number = Date.now(),
): SubagentEntry[] {
  switch (event.kind) {
    case "start": {
      // If an entry with this id already exists, replace it rather than
      // stacking duplicates (shouldn't happen, but be defensive).
      const existing = entries.some((e) => e.id === event.id);
      const entry: SubagentEntry = {
        id: event.id,
        name: event.name,
        model: event.model,
        provider: event.provider,
        depth: event.depth ?? 0,
        parentId: event.parentId,
        status: "running",
        text: "",
        thinking: "",
        toolCallCount: 0,
        startedAt: now,
      };
      return existing
        ? entries.map((e) => (e.id === event.id ? entry : e))
        : [...entries, entry];
    }

    case "text":
      return entries.map((entry) =>
        entry.id === event.id
          ? { ...entry, text: entry.text + event.delta }
          : entry,
      );

    case "thinking":
      return entries.map((entry) =>
        entry.id === event.id
          ? { ...entry, thinking: entry.thinking + event.delta }
          : entry,
      );

    case "tool_call":
      return entries.map((entry) =>
        entry.id === event.id
          ? {
              ...entry,
              toolCallCount: entry.toolCallCount + 1,
              activeTool: { name: event.name, server: event.server },
            }
          : entry,
      );

    case "tool_result":
      return entries.map((entry) =>
        entry.id === event.id ? { ...entry, activeTool: undefined } : entry,
      );

    case "done":
      return entries.map((entry) => {
        if (entry.id !== event.id) return entry;
        let status: SubagentStatus = "done";
        if (event.cancelled) status = "cancelled";
        if (event.error) status = "error";
        return {
          ...entry,
          status,
          // Only override text if the event carries a non-empty summary —
          // otherwise keep whatever we accumulated during streaming.
          text: event.text || entry.text,
          toolCallCount: event.toolCalls || entry.toolCallCount,
          promptTokens: event.promptTokens,
          completionTokens: event.completionTokens,
          error: event.error,
          activeTool: undefined,
          finishedAt: now,
        };
      });

    case "error":
      return entries.map((entry) =>
        entry.id === event.id
          ? {
              ...entry,
              status: "error",
              error: event.message,
              activeTool: undefined,
              finishedAt: now,
            }
          : entry,
      );
  }
}

/**
 * Remove entries that have finished and are older than the given age.
 * Used to prune completed subagents after a user starts a new turn
 * so the panel doesn't accumulate stale rows indefinitely.
 */
export function pruneFinishedSubagents(
  entries: SubagentEntry[],
  now: number = Date.now(),
  maxAgeMs: number = 0,
): SubagentEntry[] {
  if (maxAgeMs === 0) {
    // Remove all finished entries regardless of age
    return entries.filter((e) => e.status === "running");
  }
  return entries.filter((entry) => {
    if (entry.status === "running") return true;
    if (entry.finishedAt === undefined) return true;
    return now - entry.finishedAt < maxAgeMs;
  });
}

export interface SubagentTreeNode {
  entry: SubagentEntry;
  children: SubagentTreeNode[];
}

export function buildSubagentForest(entries: SubagentEntry[]): SubagentTreeNode[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const childMap = new Map<string, SubagentEntry[]>();
  const roots: SubagentEntry[] = [];

  for (const entry of entries) {
    if (entry.parentId && byId.has(entry.parentId) && entry.parentId !== entry.id) {
      const siblings = childMap.get(entry.parentId) ?? [];
      siblings.push(entry);
      childMap.set(entry.parentId, siblings);
      continue;
    }
    roots.push(entry);
  }

  const seen = new Set<string>();
  function visit(entry: SubagentEntry, ancestry: Set<string>): SubagentTreeNode {
    seen.add(entry.id);
    const nextAncestry = new Set(ancestry);
    nextAncestry.add(entry.id);
    const children: SubagentTreeNode[] = [];
    for (const child of childMap.get(entry.id) ?? []) {
      if (nextAncestry.has(child.id)) {
        continue;
      }
      children.push(visit(child, nextAncestry));
    }
    return {
      entry,
      children,
    };
  }

  const forest = roots.map((entry) => visit(entry, new Set()));
  for (const entry of entries) {
    if (!seen.has(entry.id)) {
      forest.push(visit(entry, new Set()));
    }
  }
  return forest;
}
