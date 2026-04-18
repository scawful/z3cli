/**
 * Live-updating streaming response with animated indicators.
 */

import React from "react";
import { Box, Text } from "ink";
import { highlightHexAddresses } from "./Markdown.js";
import { ThinkingTraceBlock } from "./ThinkingTraceBlock.js";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { showStreamingThinking } from "../utils/thinking.js";

// ---------------------------------------------------------------------------
// Animated thinking indicator
// ---------------------------------------------------------------------------

const THINKING_VERBS = [
  "thinking", "reasoning", "analyzing",
  "considering", "pondering", "examining",
] as const;

function ThinkingIndicator({ colors }: { colors: any }): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.thinking);
  const verb = useAnimatedFrame([...THINKING_VERBS], 1600);
  return (
    <Box gap={1}>
      <Text color={colors.triforce}>{spinner}</Text>
      <Text color={colors.muted}>{verb}...</Text>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Tool call spinner with elapsed time
// ---------------------------------------------------------------------------

function ToolCallSpinner({
  name,
  server,
  elapsed,
  colors,
}: {
  name: string;
  server: string;
  elapsed: number;
  colors: any;
}): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.spinner, 100);
  const label = server && server !== "unknown" ? `${server}:${name}` : name;
  return (
    <Box gap={1} paddingLeft={1}>
      <Text color={colors.tool}>{spinner}</Text>
      <Text color={colors.tool} bold>{label}</Text>
      <Text dimColor>{elapsed}s</Text>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Streaming message
// ---------------------------------------------------------------------------

interface StreamingMessageProps {
  content: string;
  thinkingContent: string;
  activeToolCall: { name: string; server: string; elapsed: number } | null;
}

export function StreamingMessage({
  content,
  thinkingContent,
  activeToolCall,
}: StreamingMessageProps): React.ReactElement {
  const { colors, settings } = useSettingsContext();
  const plainAnsi = settings.transcriptShowMessages && content ? highlightHexAddresses(content) : "";
  const visibleThinking = settings.transcriptShowReasoning && showStreamingThinking(settings.showThinking)
    ? thinkingContent
    : "";
  const visibleToolCall = settings.transcriptShowTools ? activeToolCall : null;
  const hiddenByFilters = !plainAnsi && !visibleThinking && !visibleToolCall;

  return (
    <Box flexDirection="column" paddingX={1}>
      {visibleThinking ? <ThinkingTraceBlock content={visibleThinking} mode="tail" label="live reasoning" /> : null}
      {plainAnsi ? (
        <Text wrap="wrap">{plainAnsi}</Text>
      ) : null}
      {visibleToolCall ? (
        <ToolCallSpinner
          name={visibleToolCall.name}
          server={visibleToolCall.server}
          elapsed={visibleToolCall.elapsed}
          colors={colors}
        />
      ) : plainAnsi ? null : hiddenByFilters ? (
        <Text dimColor>stream hidden by transcript filters</Text>
      ) : !visibleThinking ? (
        <ThinkingIndicator colors={colors} />
      ) : null}
    </Box>
  );
}
