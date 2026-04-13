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
import {
  colors, symbols,
  modelColor, modelSymbol,
  serverColor, serverSymbol,
} from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import type { Message } from "../ipc/protocol.js";

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

const MAX_ARG_WIDTH = 60;

function ToolArgs({ jsonStr, colored }: { jsonStr: string; colored: boolean }): React.ReactElement | null {
  if (!jsonStr) return null;
  try {
    const obj = JSON.parse(jsonStr) as Record<string, unknown>;
    if (typeof obj !== "object" || obj === null) return <Text dimColor>{jsonStr}</Text>;
    const entries = Object.entries(obj);
    if (entries.length === 0) return null;
    return (
      <Box flexDirection="column">
        {entries.map(([k, v]) => {
          const val = typeof v === "string" ? v : JSON.stringify(v);
          const display = val.length > MAX_ARG_WIDTH ? val.slice(0, MAX_ARG_WIDTH - 3) + "..." : val;
          return colored ? (
            <Box key={k} gap={1}>
              <Text color={colors.dim}>{k}:</Text>
              <Text>{display}</Text>
            </Box>
          ) : (
            <Text key={k} dimColor>{k}: {display}</Text>
          );
        })}
      </Box>
    );
  } catch {
    const display = jsonStr.length > MAX_ARG_WIDTH
      ? jsonStr.slice(0, MAX_ARG_WIDTH - 3) + "..."
      : jsonStr;
    return <Text dimColor>{display}</Text>;
  }
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

export function MessageBubble({ message }: MessageBubbleProps): React.ReactElement {
  const { settings } = useSettingsContext();
  const { role, content, toolName, toolServer, toolArguments, model } = message;

  if (role === "tool" && toolArguments !== undefined && !content) {
    const server = toolServer ?? "";
    const sc = serverColor(server);
    return (
      <Box borderStyle="round" borderColor={sc} paddingX={1} flexDirection="column">
        <Box gap={1}>
          <Text color={sc}>{serverSymbol(server)}</Text>
          {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
          <Text bold color={sc}>{toolName ?? "tool"}</Text>
        </Box>
        {toolArguments ? (
          <Box paddingLeft={2}>
            <ToolArgs jsonStr={toolArguments} colored={settings.coloredToolArgs} />
          </Box>
        ) : null}
      </Box>
    );
  }

  if (role === "tool" && content) {
    const isError = content.startsWith("Error") || content.startsWith("error:");
    const lines = content.split("\n");
    const totalLines = lines.length;
    const maxLines = 12;
    const display =
      totalLines > maxLines
        ? lines.slice(0, maxLines).join("\n") + `\n··· ${totalLines - maxLines} more lines`
        : content;
    const resultColor = isError ? colors.error : colors.success;
    return (
      <Box borderStyle="round" borderColor={resultColor} paddingX={1} flexDirection="column">
        {settings.showToolGrouping || totalLines > maxLines ? (
          <Box gap={1}>
            {settings.showToolGrouping ? <Text dimColor>└</Text> : null}
            {toolName ? <Text dimColor>{toolName}</Text> : null}
            {totalLines > maxLines
              ? <Text dimColor>{symbols.arrow} {totalLines} lines</Text>
              : null}
          </Box>
        ) : null}
        <Text dimColor>{display}</Text>
      </Box>
    );
  }

  if (role === "user") {
    return (
      <Box paddingX={1} marginTop={1}>
        <Text bold color={colors.user}>{symbols.arrowRight} </Text>
        <Text>{content}</Text>
      </Box>
    );
  }

  if (role === "system") {
    return (
      <Box flexDirection="column" paddingX={2} marginBottom={1}>
        <Markdown>{content}</Markdown>
      </Box>
    );
  }

  // Assistant
  const mc = model ? modelColor(model) : colors.assistant;
  const ms = model ? modelSymbol(model) : symbols.triforceSmall;
  return (
    <Box flexDirection="column" paddingX={2} marginBottom={1}>
      {model ? (
        <Box justifyContent="space-between">
          <Text color={mc}>{ms} <Text bold>{model}</Text></Text>
          {settings.showTimestamps
            ? <Text dimColor>{formatTime(message.timestamp)}</Text>
            : null}
        </Box>
      ) : settings.showTimestamps ? (
        <Box justifyContent="flex-end">
          <Text dimColor>{formatTime(message.timestamp)}</Text>
        </Box>
      ) : null}
      <Markdown>{content}</Markdown>
    </Box>
  );
}
