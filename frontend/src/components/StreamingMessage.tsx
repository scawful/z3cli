/**
 * Live-updating streaming response with animated indicators.
 */

import React from "react";
import { Box, Text } from "ink";
import { Markdown } from "./Markdown.js";
import { colors, symbols } from "../theme/index.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";

// ---------------------------------------------------------------------------
// Animated thinking indicator
// ---------------------------------------------------------------------------

const THINKING_VERBS = [
  "thinking", "reasoning", "analyzing",
  "considering", "pondering", "examining",
] as const;

function ThinkingIndicator(): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.thinking);
  // Advance verb every ~20 frames at 80ms = ~1.6s per verb
  const [verbIndex, setVerbIndex] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setVerbIndex((i) => (i + 1) % THINKING_VERBS.length), 1600);
    return () => clearInterval(t);
  }, []);
  return (
    <Box gap={1}>
      <Text color={colors.triforce}>{spinner}</Text>
      <Text color={colors.muted}>{THINKING_VERBS[verbIndex]}...</Text>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Thinking content (last N lines of extended reasoning)
// ---------------------------------------------------------------------------

function ThinkingBlock({ content }: { content: string }): React.ReactElement {
  const lines = content.split("\n");
  const display = lines.length > 6 ? lines.slice(-6).join("\n") : content;
  return (
    <Box
      borderStyle="round"
      borderColor={colors.dim}
      paddingX={1}
      flexDirection="column"
    >
      <Box gap={1}>
        <Text color={colors.muted}>{symbols.thinking[0]}</Text>
        <Text dimColor>reasoning</Text>
        {lines.length > 6 ? <Text dimColor>({lines.length} lines)</Text> : null}
      </Box>
      <Text dimColor>{display}</Text>
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
}: {
  name: string;
  server: string;
  elapsed: number;
}): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.spinner, 100);
  const label = server && server !== "unknown" ? `${server}:${name}` : name;
  return (
    <Box borderStyle="round" borderColor={colors.tool} paddingX={1} gap={1}>
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
  return (
    <Box flexDirection="column">
      {thinkingContent ? <ThinkingBlock content={thinkingContent} /> : null}
      {content ? <Markdown>{content}</Markdown> : null}
      {activeToolCall ? (
        <ToolCallSpinner
          name={activeToolCall.name}
          server={activeToolCall.server}
          elapsed={activeToolCall.elapsed}
        />
      ) : content ? null : !thinkingContent ? (
        <ThinkingIndicator />
      ) : null}
    </Box>
  );
}
