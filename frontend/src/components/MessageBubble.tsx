/**
 * Renders a single message with role-based Zelda styling.
 *
 * Tool calls get server-themed borders with colored key/value arguments.
 * Tool results show a grouping header and truncate long output.
 * Assistant messages show model attribution and optional timestamp.
 */

import React from "react";
import { Box, Text } from "ink";
import { Markdown } from "./Markdown.js";
import { JsonArgList } from "./JsonArgList.js";
import {
  symbols,
  modelColor, modelSymbol,
  serverColor, serverSymbol,
  toolSymbol,
} from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import type { Message } from "../ipc/protocol.js";
import {
  collapseToolResult,
  parseToolArguments,
  summarizeToolInvocation,
  summarizeToolResult,
} from "../utils/tooling.js";
import { constructToken } from "../utils/prompt.js";
import { showTranscriptThinking } from "../utils/thinking.js";
import { ThinkingTraceBlock } from "./ThinkingTraceBlock.js";

interface MessageBubbleProps {
  message: Message;
}

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function shouldRenderToolResultAsMarkdown(content: string): boolean {
  const t = content.trim();
  if (t.includes("```")) return true;
  if (content.includes("\n")) return true;
  if (t.startsWith("{") || t.startsWith("[")) {
    try {
      JSON.parse(t);
      return true;
    } catch {
      return t.length > 40;
    }
  }
  return t.length > 160;
}

function isDeniedToolResult(content: string): boolean {
  return content.trim() === "[Tool call denied by user]";
}

function AttachmentList({
  attachments,
}: {
  attachments: NonNullable<Message["attachments"]>;
}): React.ReactElement | null {
  const { colors } = useSettingsContext();
  if (attachments.length === 0) return null;
  return (
    <Box flexDirection="column" paddingLeft={2}>
      <Box gap={1}>
        <Text dimColor>{symbols.triforceSmall}</Text>
        <Text dimColor>attached files</Text>
      </Box>
      {attachments.map((attachment) => (
        <Box key={attachment.path} gap={1} paddingLeft={2}>
          <Text color={colors.nayru}>{attachment.path}</Text>
          <Text dimColor>{attachment.lines}L</Text>
          <Text dimColor>{attachment.chars}C</Text>
        </Box>
      ))}
    </Box>
  );
}

function ConstructRefList({
  constructRefs,
}: {
  constructRefs: NonNullable<Message["constructRefs"]>;
}): React.ReactElement | null {
  const { colors } = useSettingsContext();
  if (constructRefs.length === 0) return null;
  return (
    <Box flexDirection="column" paddingLeft={2}>
      <Box gap={1}>
        <Text dimColor>{symbols.triforceSmall}</Text>
        <Text dimColor>game refs</Text>
      </Box>
      {constructRefs.map((ref) => (
        <Box key={constructToken(ref)} gap={1} paddingLeft={2}>
          <Text color={colors.accent}>{constructToken(ref)}</Text>
          {ref.label ? <Text dimColor>{ref.label}</Text> : null}
        </Box>
      ))}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

export function MessageBubble({ message }: MessageBubbleProps): React.ReactElement {
  const { settings, colors } = useSettingsContext();
  const { role, content, toolName, toolServer, toolArguments, model, attachments, constructRefs, thinking } = message;

  if (role === "tool" && toolArguments !== undefined && !content) {
    const server = toolServer ?? "";
    const sc = serverColor(server, colors);
    const ts = toolSymbol(toolName ?? "tool");
    const args = parseToolArguments(toolArguments);
    const summary = summarizeToolInvocation(toolName ?? "tool", args);
    const showArgs = toolArguments.trim().length > 0 && toolArguments.trim().length <= 220;
    return (
      <Box flexDirection="column" paddingLeft={1}>
        <Box gap={1}>
          <Text color={sc}>{ts}</Text>
          {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
          <Text bold color={sc}>{toolName ?? "tool"}</Text>
          {summary && summary !== (toolName ?? "tool") ? (
            <Text dimColor>{symbols.dot} {summary}</Text>
          ) : null}
        </Box>
        {showArgs ? (
          <Box paddingLeft={2}>
            <JsonArgList jsonStr={toolArguments} colored={settings.coloredToolArgs} />
          </Box>
        ) : null}
      </Box>
    );
  }

  if (role === "tool" && content) {
    const isError = content.startsWith("Error") || content.startsWith("error:");
    const denied = isDeniedToolResult(content);
    const collapsed = collapseToolResult(content);
    const display = collapsed.display;
    const resultColor = denied ? colors.warning : (isError ? colors.error : colors.success);
    const rich = !denied && shouldRenderToolResultAsMarkdown(display);
    const summary = summarizeToolResult(content);
    return (
      <Box flexDirection="column" paddingLeft={1}>
        <Box gap={1}>
          {settings.showToolGrouping ? <Text dimColor>└</Text> : null}
          {toolName ? <Text color={resultColor}>{toolSymbol(toolName)} {toolName}</Text> : null}
          <Text dimColor>{symbols.arrow}</Text>
          <Text color={resultColor}>{summary}</Text>
        </Box>
        {denied ? null : rich ? (
          <Box paddingLeft={1}>
            <Markdown>{display}</Markdown>
          </Box>
        ) : (
          <Box paddingLeft={1}>
            <Text dimColor>{display}</Text>
          </Box>
        )}
        {collapsed.wasCollapsed ? (
          collapsed.hiddenLines > 0 ? (
            <Box paddingLeft={1}>
              <Text dimColor>··· {collapsed.hiddenLines} more lines</Text>
            </Box>
          ) : collapsed.truncatedByChars ? (
            <Box paddingLeft={1}>
              <Text dimColor>··· output truncated</Text>
            </Box>
          ) : null
        ) : null}
      </Box>
    );
  }

  if (role === "user") {
    return (
      <Box
        marginTop={1}
        marginBottom={1}
        paddingLeft={1}
        borderStyle="single"
        borderColor={colors.user}
        borderTop={false}
        borderBottom={false}
        borderRight={false}
        flexDirection="column"
      >
        <Box justifyContent="space-between">
          <Box gap={1}>
            <Text bold color={colors.user}>{symbols.arrowRight} you</Text>
          </Box>
          {settings.showTimestamps
            ? <Text dimColor>{formatTime(message.timestamp)}</Text>
            : null}
        </Box>
        <Text wrap="wrap">{content}</Text>
        {attachments && attachments.length > 0 ? (
          <AttachmentList attachments={attachments} />
        ) : null}
        {constructRefs && constructRefs.length > 0 ? (
          <ConstructRefList constructRefs={constructRefs} />
        ) : null}
      </Box>
    );
  }

  if (role === "system") {
    return (
      <Box
        marginTop={1}
        marginBottom={1}
        paddingLeft={1}
        borderStyle="single"
        borderColor={colors.nayru}
        borderTop={false}
        borderBottom={false}
        borderRight={false}
        flexDirection="column"
      >
        <Box gap={1}>
          <Text color={colors.nayru} bold>[Navi]</Text>
          <Text italic dimColor>Hey! Listen!</Text>
        </Box>
        <Markdown>{content}</Markdown>
      </Box>
    );
  }

  // Assistant
  const visibleThinking = showTranscriptThinking(settings.showThinking) ? thinking : undefined;
  if (!content.trim() && !visibleThinking) {
    return <></>;
  }
  const mc = model ? modelColor(model, colors) : colors.assistant;
  const ms = model ? modelSymbol(model) : symbols.triforceSmall;
  return (
    <Box
      marginTop={1}
      marginBottom={1}
      paddingLeft={1}
      borderStyle="single"
      borderColor={mc}
      borderTop={false}
      borderBottom={false}
      borderRight={false}
      flexDirection="column"
    >
      <Box justifyContent="space-between" gap={1}>
        <Box gap={1}>
          <Text color={mc}>{ms}</Text>
          <Text bold color={mc}>{model || "Oracle"}</Text>
        </Box>
        {settings.showTimestamps
          ? <Text dimColor>{formatTime(message.timestamp)}</Text>
          : null}
      </Box>
      <Box flexDirection="column" paddingLeft={1}>
        {visibleThinking ? <ThinkingTraceBlock content={visibleThinking} mode="head" label="reasoning trace" /> : null}
        {content.trim() ? <Markdown>{content}</Markdown> : null}
      </Box>
    </Box>
  );
}
