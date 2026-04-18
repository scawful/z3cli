import React from "react";
import { Box, Text, useInput } from "ink";
import { symbols, serverColor, serverSymbol } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";

interface ToolReviewDialogProps {
  name: string;
  server: string;
  summary: string;
  paths: string[];
  diffLines: string[];
  omitted: number;
  verificationCommands: string[];
  onAccept: () => void;
  onReject: () => void;
}

interface DialogColors {
  success: string;
  error: string;
  warning: string;
  muted: string;
}

function lineColor(line: string, colors: DialogColors): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return colors.success;
  if (line.startsWith("-") && !line.startsWith("---")) return colors.error;
  if (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) return colors.warning;
  return colors.muted;
}

const actionPrompts = [
  "Y/Enter keep changes",
  "N/Esc revert",
];

export function ToolReviewDialog({
  name,
  server,
  summary,
  paths,
  diffLines,
  omitted,
  verificationCommands,
  onAccept,
  onReject,
}: ToolReviewDialogProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const sc = serverColor(server, colors);

  useInput((input, key) => {
    if (key.return || input === "\r" || input === "\n" || input === "y" || input === "Y") {
      onAccept();
      return;
    }
    if (key.escape || input === "n" || input === "N") {
      onReject();
    }
  });

  return (
    <Box borderStyle="double" borderColor={colors.warning} paddingX={1} flexDirection="column" marginY={1}>
      <Box gap={1} marginBottom={1} justifyContent="center">
        <Text bold color={colors.warning}>{symbols.triforce} REVIEW TOOL OUTPUT {symbols.triforce}</Text>
      </Box>
      <Box gap={1} paddingLeft={1}>
        <Text color={sc}>{serverSymbol(server)}</Text>
        {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
        <Text bold color={sc}>{name}</Text>
      </Box>
      <Text dimColor>{"  "}summary {symbols.arrow} {summary}</Text>
      {paths.length > 0 ? (
        <Text dimColor>{"  "}targets {symbols.arrow} {paths.join(", ")}</Text>
      ) : null}
      <Box borderStyle="round" borderColor={colors.warning} paddingX={1} flexDirection="column" marginTop={1}>
        <Text color={colors.warning}>diff preview</Text>
        {diffLines.map((line, index) => (
          <Text key={`${index}-${line}`} color={lineColor(line, colors)}>
            {line}
          </Text>
        ))}
        {omitted > 0 ? (
          <Text dimColor>··· {omitted} more lines</Text>
        ) : null}
      </Box>
      {verificationCommands.length > 0 ? (
        <Box flexDirection="column" paddingLeft={1} marginTop={1}>
          <Text color={colors.warning}>verification on accept</Text>
          {verificationCommands.map((command) => (
            <Text key={command} dimColor>{"  "}{command}</Text>
          ))}
        </Box>
      ) : null}
      <Box marginTop={1} flexDirection="column">
        {actionPrompts.map((prompt) => (
          <Text key={prompt} dimColor>{"  "}{prompt}</Text>
        ))}
      </Box>
    </Box>
  );
}
