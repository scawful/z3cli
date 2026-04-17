/**
 * Live panel showing active and recently-finished subagents.
 *
 * Each entry renders in its own bordered row with a spinner (running),
 * checkmark (done), or X (error). Streaming text preview shows the last
 * few lines of the subagent's output.
 */

import React from "react";
import { Box, Text } from "ink";
import { modelColor, modelSymbol, symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { buildSubagentForest, type SubagentEntry, type SubagentTreeNode } from "../utils/subagentState.js";

const PREVIEW_LINES = 4;

function statusIndicator(status: SubagentEntry["status"], colors: any): { symbol: string; color: string } {
  switch (status) {
    case "running":   return { symbol: symbols.spinner[0] ?? "*", color: colors.tool };
    case "done":      return { symbol: "✓", color: colors.success };
    case "error":     return { symbol: "✗", color: colors.error };
    case "cancelled": return { symbol: "⊘", color: colors.warning };
  }
}

function formatDuration(startedAt: number, finishedAt?: number): string {
  const end = finishedAt ?? Date.now();
  const seconds = Math.max(0, Math.round((end - startedAt) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${mins}m${rem > 0 ? `${rem}s` : ""}`;
}

function lastLines(text: string, count: number): string {
  const lines = text.split("\n");
  if (lines.length <= count) return text.trim();
  return lines.slice(-count).join("\n").trim();
}

function RunningSpinner({ color }: { color: string }): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.spinner, 100);
  return <Text color={color}>{spinner}</Text>;
}

function SubagentRow({
  entry,
  level,
}: {
  entry: SubagentEntry;
  level: number;
}): React.ReactElement {
  const { colors } = useSettingsContext();
  const tint = modelColor(entry.model, colors);
  const marker = modelSymbol(entry.model);
  const indicator = statusIndicator(entry.status, colors);
  const duration = formatDuration(entry.startedAt, entry.finishedAt);
  const isNested = level > 0;

  const preview =
    entry.status === "running"
      ? lastLines(entry.text, PREVIEW_LINES)
      : entry.text.trim();

  const showPreview = preview.length > 0;
  const showError = entry.status === "error" && entry.error;

  return (
    <Box paddingLeft={level * 2} flexDirection="column">
      <Box
        borderStyle="double"
        borderColor={entry.status === "error" ? colors.error : colors.border}
        paddingX={1}
        flexDirection="column"
      >
      <Box gap={1}>
        {entry.status === "running" ? (
          <RunningSpinner color={indicator.color} />
        ) : (
          <Text color={indicator.color}>{indicator.symbol}</Text>
        )}
        {isNested ? <Text dimColor>↳</Text> : null}
        <Text color={tint} bold>
          {marker} {entry.name}
        </Text>
        {entry.provider && entry.provider !== "studio" ? (
          <Text dimColor>({entry.provider})</Text>
        ) : null}
        {entry.depth > 0 ? <Text dimColor>· d{entry.depth}</Text> : null}
        <Text dimColor>· {duration}</Text>
        {entry.toolCallCount > 0 ? (
          <Text dimColor>
            · {symbols.triforceSmall} {entry.toolCallCount}
          </Text>
        ) : null}
        {entry.activeTool ? (
          <Text color={colors.tool}>
            → {entry.activeTool.server
              ? `${entry.activeTool.server}:${entry.activeTool.name}`
              : entry.activeTool.name}
          </Text>
        ) : null}
        {entry.status === "done" && entry.completionTokens !== undefined ? (
          <Text dimColor>
            · {entry.promptTokens ?? 0}/{entry.completionTokens ?? 0} tok
          </Text>
        ) : null}
      </Box>
      {showError ? (
        <Text color={colors.error}>{entry.error}</Text>
      ) : null}
      {showPreview && !showError ? (
        <Text dimColor>{preview}</Text>
      ) : null}
      </Box>
    </Box>
  );
}

function SubagentNode({
  node,
  level,
}: {
  node: SubagentTreeNode;
  level: number;
}): React.ReactElement {
  return (
    <Box flexDirection="column">
      <SubagentRow entry={node.entry} level={level} />
      {node.children.map((child) => (
        <SubagentNode key={child.entry.id} node={child} level={level + 1} />
      ))}
    </Box>
  );
}

interface SubagentPanelProps {
  entries: SubagentEntry[];
}

export function SubagentPanel({ entries }: SubagentPanelProps): React.ReactElement | null {
  const { colors } = useSettingsContext();
  if (entries.length === 0) return null;
  const running = entries.filter((e) => e.status === "running").length;
  const forest = buildSubagentForest(entries);
  return (
    <Box flexDirection="column" paddingX={2} marginTop={1}>
      <Box gap={1} marginBottom={1}>
        <Text color={colors.triforce} bold>
          {symbols.triforce} Side Quests (Subagents)
        </Text>
        <Text dimColor>
          ({running > 0 ? `${running} active · ` : ""}{entries.length} total)
        </Text>
      </Box>
      {forest.map((node) => (
        <SubagentNode key={node.entry.id} node={node} level={0} />
      ))}
    </Box>
  );
}
