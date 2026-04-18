import React from "react";
import { Box, Text } from "ink";
import { highlightHexAddresses } from "./Markdown.js";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { buildThinkingDisplay, prefixThinkingLines } from "../utils/thinking.js";
import { ReasoningToggleButton } from "./ReasoningToggleButton.js";

interface ThinkingTraceBlockProps {
  content: string;
  mode: "head" | "tail";
  label?: string;
  compact?: boolean;
}

export function ThinkingTraceBlock({
  content,
  mode,
  label = "reasoning trace",
  compact = false,
}: ThinkingTraceBlockProps): React.ReactElement | null {
  const { colors, settings } = useSettingsContext();
  const preview = buildThinkingDisplay(content, settings.thinkingDetail, { mode });
  if (!preview.text) return null;

  return (
    <Box
      borderStyle={compact ? "round" : "double"}
      borderColor={colors.nayru}
      paddingX={1}
      marginBottom={1}
      flexDirection="column"
    >
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text color={colors.nayru}>{symbols.crystal}</Text>
          <Text color={colors.nayru} bold>{label.toUpperCase()}</Text>
          <Text dimColor>{preview.lineCount} lines</Text>
        </Box>
        <ReasoningToggleButton />
      </Box>
      <Text color={colors.muted}>separate internal reasoning stream</Text>
      <Text dimColor>{highlightHexAddresses(prefixThinkingLines(preview.text))}</Text>
      {preview.truncated && preview.overflowLabel ? (
        <Text dimColor>··· {preview.overflowLabel}</Text>
      ) : null}
    </Box>
  );
}
