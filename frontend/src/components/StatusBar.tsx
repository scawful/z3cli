/**
 * Compact status line below the prompt.
 * Model · workspace · focus file — tokens · warnings · tools · counters.
 */

import React from "react";
import { Box, Text } from "ink";
import { symbols, modelColor, formatTokens, uiModeColor } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { shortenPath, basename } from "../utils/path.js";
import { formatCacheCompact } from "../utils/cacheMetrics.js";
import type { UIMode } from "../hooks/useSettings.js";

interface StatusBarProps {
  model: string;
  serverCount: number;
  toolCount: number;
  messageCount: number;
  promptTokens: number;
  completionTokens: number;
  cacheReadTokens?: number;
  cacheCreationTokens?: number;
  isStreaming: boolean;
  workspace: string;
  warningCount: number;
  toolsEnabled: boolean;
  focusFile?: string;
}

export function StatusBar({
  model,
  serverCount,
  toolCount,
  messageCount,
  promptTokens,
  completionTokens,
  cacheReadTokens = 0,
  cacheCreationTokens = 0,
  isStreaming,
  workspace,
  warningCount,
  toolsEnabled,
  focusFile,
}: StatusBarProps): React.ReactElement {
  const { settings, colors } = useSettingsContext();
  const tok = formatTokens(promptTokens + completionTokens, colors);
  const focusName = focusFile ? basename(focusFile) : "";
  const cacheBadge = formatCacheCompact(cacheReadTokens, cacheCreationTokens);

  return (
    <Box width="100%" paddingX={1} justifyContent="space-between">
      <Box gap={1}>
        <Text color={isStreaming ? colors.triforce : colors.dim}>{symbols.triforceSmall}</Text>
        <Text bold color={modelColor(model, colors)}>{model}</Text>
        <Text dimColor>{symbols.dot}</Text>
        <Text dimColor>{shortenPath(workspace)}</Text>
        {settings.showFocusFile && focusName ? (
          <>
            <Text dimColor>{symbols.dot}</Text>
            <Text color={colors.nayru}>{symbols.pendant} {focusName}</Text>
          </>
        ) : null}
      </Box>
      <Box gap={1}>
        {tok.text ? (
          <>
            <Text color={tok.color}>{tok.text}</Text>
            <Text dimColor>{symbols.dot}</Text>
          </>
        ) : null}
        {cacheBadge ? (
          <>
            <Text color={colors.muted}>{symbols.rupee} {cacheBadge}</Text>
            <Text dimColor>{symbols.dot}</Text>
          </>
        ) : null}
        {warningCount > 0 ? (
          <>
            <Text color={colors.warning}>{warningCount} warn</Text>
            <Text dimColor>{symbols.dot}</Text>
          </>
        ) : null}
        {settings.toolsIndicator ? (
          <>
            <Text color={toolsEnabled ? colors.tool : colors.dim}>{symbols.sword}</Text>
            <Text dimColor>{symbols.dot}</Text>
          </>
        ) : null}
        <Text dimColor>{serverCount}s {toolCount}t {messageCount}m</Text>
        <Text dimColor>{symbols.dot}</Text>
        <Text color={uiModeColor(settings.uiMode, colors)} bold={settings.uiMode !== "chat"}>
          {settings.uiMode}
        </Text>
      </Box>
    </Box>
  );
}
