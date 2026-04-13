/**
 * Compact status line below the prompt.
 * Model · workspace · focus file — tokens · warnings · tools · counters.
 */

import React from "react";
import { Box, Text } from "ink";
import { colors, symbols, modelColor, formatTokens } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { shortenPath, basename } from "../utils/path.js";
import type { UIMode } from "../hooks/useSettings.js";

function uiModeColor(mode: UIMode): string {
  switch (mode) {
    case "admin":  return colors.din;
    case "build":  return colors.farore;
    case "plan":   return colors.nayru;
    case "review": return colors.triforce;
    default:       return colors.dim;
  }
}

interface StatusBarProps {
  model: string;
  serverCount: number;
  toolCount: number;
  messageCount: number;
  promptTokens: number;
  completionTokens: number;
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
  isStreaming,
  workspace,
  warningCount,
  toolsEnabled,
  focusFile,
}: StatusBarProps): React.ReactElement {
  const { settings } = useSettingsContext();
  const tok = formatTokens(promptTokens + completionTokens);
  const focusName = focusFile ? basename(focusFile) : "";

  return (
    <Box paddingX={1} justifyContent="space-between">
      <Box gap={1}>
        <Text color={isStreaming ? colors.triforce : colors.dim}>{symbols.triforceSmall}</Text>
        <Text bold color={modelColor(model)}>{model}</Text>
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
        <Text color={uiModeColor(settings.uiMode)} bold={settings.uiMode !== "chat"}>
          {settings.uiMode}
        </Text>
      </Box>
    </Box>
  );
}
