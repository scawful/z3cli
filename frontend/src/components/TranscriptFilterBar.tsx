import React from "react";
import { Box, Text } from "ink";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { symbols } from "../theme/index.js";

function FilterBadge({
  label,
  enabled,
  activeColor,
}: {
  label: string;
  enabled: boolean;
  activeColor: string;
}): React.ReactElement {
  const { colors } = useSettingsContext();
  return (
    <Text color={enabled ? activeColor : colors.dim}>
      {enabled ? "[x]" : "[ ]"} {label}
    </Text>
  );
}

export function TranscriptFilterBar(): React.ReactElement {
  const { colors, settings } = useSettingsContext();
  const reasoningLabel = !settings.transcriptShowReasoning || settings.showThinking === "off"
    ? "off"
    : settings.showThinking === "streamed-only"
      ? "live-only"
      : settings.collapseReasoning
        ? "summary"
        : settings.thinkingDetail;

  return (
    <Box width="100%" paddingX={1} justifyContent="space-between">
      <Box gap={1} flexWrap="wrap">
        <Text color={colors.triforce}>{symbols.triforceSmall}</Text>
        <Text dimColor>transcript</Text>
        <Text dimColor>{symbols.dot}</Text>
        <FilterBadge label="messages" enabled={settings.transcriptShowMessages} activeColor={colors.text} />
        <FilterBadge label={`reason ${reasoningLabel}`} enabled={settings.transcriptShowReasoning} activeColor={colors.nayru} />
        <FilterBadge label="tools" enabled={settings.transcriptShowTools} activeColor={colors.tool} />
        <FilterBadge label="subagents" enabled={settings.transcriptShowSubagents} activeColor={colors.accent} />
      </Box>
      <Text dimColor>
        <Text color={colors.triforce}>[Alt+M/R/T/A]</Text> filters {symbols.dot} <Text color={colors.triforce}>[Ctrl+R]</Text> summary
      </Text>
    </Box>
  );
}
