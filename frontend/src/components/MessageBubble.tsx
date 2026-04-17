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
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import type { Message } from "../ipc/protocol.js";
import {
  collapseToolResult,
  parseToolArguments,
  summarizeToolInvocation,
  summarizeToolResult,
} from "../utils/tooling.js";

interface MessageBubbleProps {
  message: Message;
}

// ---------------------------------------------------------------------------
// File-local helpers
// ---------------------------------------------------------------------------

function Blinker({ color }: { color: string }): React.ReactElement {
  const frame = useAnimatedFrame(["▼", " "], 600);
  return <Text color={color}>{frame}</Text>;
}

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

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

export function MessageBubble({ message }: MessageBubbleProps): React.ReactElement {
  const { settings, colors } = useSettingsContext();
  const { role, content, toolName, toolServer, toolArguments, model, attachments } = message;

  if (role === "tool" && toolArguments !== undefined && !content) {
    const server = toolServer ?? "";
    const sc = serverColor(server, colors);
    const ts = toolSymbol(toolName ?? "tool");
    const args = parseToolArguments(toolArguments);
    const summary = summarizeToolInvocation(toolName ?? "tool", args);
    const showArgs = toolArguments.trim().length > 0 && toolArguments.trim().length <= 220;
    return (
      <Box borderStyle="round" borderColor={sc} paddingX={1} flexDirection="column">
        <Box gap={1}>
          <Text color={sc}>{ts}</Text>
          {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
          <Text bold color={sc}>{toolName ?? "tool"}</Text>
        </Box>
        {summary && summary !== (toolName ?? "tool") ? (
          <Text dimColor>{summary}</Text>
        ) : null}
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
    const collapsed = collapseToolResult(content);
    const display = collapsed.display;
    const resultColor = isError ? colors.error : colors.success;
    const rich = shouldRenderToolResultAsMarkdown(display);
    const summary = summarizeToolResult(content);
    return (
      <Box borderStyle="round" borderColor={resultColor} paddingX={1} flexDirection="column">
        <Box gap={1}>
          {settings.showToolGrouping ? <Text dimColor>└</Text> : null}
          {toolName ? <Text dimColor>{toolSymbol(toolName)} {toolName}</Text> : null}
          <Text dimColor>{symbols.arrow} {summary}</Text>
        </Box>
        {rich ? (
          <Markdown>{display}</Markdown>
        ) : (
          <Text dimColor>{display}</Text>
        )}
        {collapsed.wasCollapsed ? (
          collapsed.hiddenLines > 0 ? (
            <Text dimColor>··· {collapsed.hiddenLines} more lines</Text>
          ) : collapsed.truncatedByChars ? (
            <Text dimColor>··· output truncated</Text>
          ) : null
        ) : null}
      </Box>
    );
  }

  if (role === "user") {
    return (
      <Box paddingX={1} marginTop={1} flexDirection="column">
        <Box>
          <Text bold color={colors.user}>{symbols.arrowRight} </Text>
          <Text wrap="wrap">{content}</Text>
        </Box>
        {attachments && attachments.length > 0 ? (
          <AttachmentList attachments={attachments} />
        ) : null}
      </Box>
    );
  }

  if (role === "system") {
    return (
      <Box flexDirection="column" paddingX={2} marginBottom={1}>
        <Box gap={1}>
          <Text color={colors.nayru} bold>[Navi]</Text>
          <Text italic dimColor>Hey! Listen!</Text>
        </Box>
        <Markdown>{content}</Markdown>
      </Box>
    );
  }

  // Assistant
  const mc = model ? modelColor(model, colors) : colors.assistant;
  const ms = model ? modelSymbol(model) : symbols.triforceSmall;
  return (
    <Box
      borderStyle="double"
      borderColor={colors.triforce}
      paddingX={1}
      marginX={1}
      marginBottom={1}
      flexDirection="column"
    >
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text color={mc}>{ms}</Text>
          <Text bold color={mc}>{model || "Oracle"}</Text>
        </Box>
        {settings.showTimestamps
          ? <Text dimColor>{formatTime(message.timestamp)}</Text>
          : null}
      </Box>
      <Box flexDirection="column">
        <Markdown>{content}</Markdown>
      </Box>
      <Box justifyContent="flex-end">
        <Blinker color={colors.triforce} />
      </Box>
    </Box>
  );
}
