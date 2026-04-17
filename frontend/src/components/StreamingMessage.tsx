/**
 * Live-updating streaming response with animated indicators.
 */

import React, { useEffect, useState } from "react";
import { Box, Text } from "ink";
import { Markdown, highlightHexAddresses } from "./Markdown.js";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";

// ---------------------------------------------------------------------------
// Animated thinking indicator
// ---------------------------------------------------------------------------

const THINKING_VERBS = [
  "thinking", "reasoning", "analyzing",
  "considering", "pondering", "examining",
] as const;

const SHORT_SINGLE_LINE_PLAIN = 48;
const MARKDOWN_DEBOUNCE_MS = 90;
/** Prefer markdown once this many chars arrived (avoids waiting on debounce for long streams). */
const MARKDOWN_IMMEDIATE_CHARS = 200;

/**
 * Prefer plain text while markdown would be unstable (unclosed fences, partial
 * emphasis) or for tiny single-line chunks.
 */
function streamingPrefersPlainText(content: string): boolean {
  const t = content.trim();
  if (t.length === 0) return true;
  if (t.length < SHORT_SINGLE_LINE_PLAIN && !content.includes("\n")) return true;

  const fenceParts = content.split("```");
  if (fenceParts.length > 1 && fenceParts.length % 2 === 0) return true;

  const tildeFence = content.split("~~~");
  if (tildeFence.length > 1 && tildeFence.length % 2 === 0) return true;

  const tail = content.slice(-320);
  const doubleStars = (tail.match(/\*\*/g) ?? []).length;
  if (doubleStars % 2 === 1) return true;

  if (/\[[^\]]*$/.test(content)) return true;

  const lastLine = content.split("\n").pop() ?? "";
  if (/^\s{0,3}[-*+]\s+[^\n]*$/.test(lastLine) && lastLine.length < 200) return true;

  return false;
}

/**
 * After plain-mode heuristics clear, wait briefly before markdown so rapid
 * token updates do not thrash the parser; long or paragraph text opens immediately.
 */
function useStreamingMarkdownEnabled(content: string): boolean {
  const preferPlain = content ? streamingPrefersPlainText(content) : true;
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    if (!content || preferPlain) {
      setEnabled(false);
      return;
    }
    if (
      content.length >= MARKDOWN_IMMEDIATE_CHARS ||
      content.includes("\n\n") ||
      content.split("\n").length >= 4
    ) {
      setEnabled(true);
      return;
    }
    const id = setTimeout(() => setEnabled(true), MARKDOWN_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [content, preferPlain]);

  return Boolean(content) && enabled && !preferPlain;
}

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
// Thinking content (last N lines of extended reasoning)
// ---------------------------------------------------------------------------

function ThinkingBlock({ content, colors }: { content: string, colors: any }): React.ReactElement {
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
      <Text dimColor>{highlightHexAddresses(display)}</Text>
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
  const { colors } = useSettingsContext();
  const useMarkdown = useStreamingMarkdownEnabled(content);
  const plainAnsi = content ? highlightHexAddresses(content) : "";

  return (
    <Box flexDirection="column" paddingX={2}>
      {thinkingContent ? <ThinkingBlock content={thinkingContent} colors={colors} /> : null}
      {content ? (
        useMarkdown ? (
          <Markdown>{content}</Markdown>
        ) : (
          <Text wrap="wrap">{plainAnsi}</Text>
        )
      ) : null}
      {activeToolCall ? (
        <ToolCallSpinner
          name={activeToolCall.name}
          server={activeToolCall.server}
          elapsed={activeToolCall.elapsed}
          colors={colors}
        />
      ) : content ? null : !thinkingContent ? (
        <ThinkingIndicator colors={colors} />
      ) : null}
    </Box>
  );
}
