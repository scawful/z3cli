/**
 * Tool permission prompt — shown before each tool execution in non-admin modes.
 * Supports one-shot and sticky session-scoped decisions.
 */

import React, { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";
import { symbols, serverColor, serverSymbol } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { JsonArgList } from "./JsonArgList.js";
import type { ToolPreview } from "../utils/tooling.js";
import { buildToolPreview } from "../utils/tooling.js";

interface PermissionDialogProps {
  name: string;
  server: string;
  workspace: string;
  arguments: string;
  /**
   * Optional backend-supplied explanation for why approval is being requested
   * (sticky-deny rule, write-access policy, subagent spawn, etc). Rendered
   * inline under the tool header when present.
   */
  reason?: string;
  onApproveOnce: () => void;
  onApproveSession: () => void;
  onDenyOnce: () => void;
  onDenySession: () => void;
}

const actionPrompts = [
  "Y/Enter allow once",
  "A allow for session",
  "N/Esc deny once",
  "D deny for session",
];

export function PermissionDialog({
  name,
  server,
  workspace,
  arguments: args,
  reason,
  onApproveOnce,
  onApproveSession,
  onDenyOnce,
  onDenySession,
}: PermissionDialogProps): React.ReactElement {
  const { colors, settings } = useSettingsContext();
  const sc = serverColor(server, colors);
  const [preview, setPreview] = useState<ToolPreview | null>(null);

  useEffect(() => {
    let cancelled = false;
    void buildToolPreview(name, args, workspace).then((nextPreview) => {
      if (!cancelled) setPreview(nextPreview);
    });
    return () => {
      cancelled = true;
    };
  }, [args, name, workspace]);

  useInput((input, key) => {
    if (key.return || input === "\r" || input === "\n" || input === "y" || input === "Y") { onApproveOnce(); return; }
    if (input === "a" || input === "A") { onApproveSession(); return; }
    if (key.escape || input === "n" || input === "N") { onDenyOnce(); return; }
    if (input === "d" || input === "D") { onDenySession(); return; }
  });

  return (
    <Box borderStyle="double" borderColor={colors.warning} paddingX={1} flexDirection="column" marginY={1}>
      <Box gap={1} marginBottom={1} justifyContent="center">
        <Text bold color={colors.warning}>{symbols.triforce} THE ORACLE REQUESTS ACTION {symbols.triforce}</Text>
      </Box>
      <Box gap={1} paddingLeft={1}>
        <Text color={sc}>{serverSymbol(server)}</Text>
        {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
        <Text bold color={sc}>{name}</Text>
        {preview?.isWrite ? <Text color={colors.warning}>write</Text> : null}
      </Box>
      <Text dimColor>{"  "}summary {symbols.arrow} {preview?.summary ?? "pending tool preview"}</Text>
      {preview?.targetPath ? (
        <Text dimColor>{"  "}target {symbols.arrow} {preview.targetPath}</Text>
      ) : null}
      {reason ? (
        <Box paddingLeft={1} marginTop={1}>
          <Text color={colors.warning}>why {symbols.arrow} </Text>
          <Text>{reason}</Text>
        </Box>
      ) : null}
      {preview && preview.lines.length > 0 ? (
        <Box borderStyle="round" borderColor={colors.warning} paddingX={1} flexDirection="column" marginTop={1}>
          <Text color={colors.warning}>{preview.isWrite ? "diff preview" : "argument preview"}</Text>
          {preview.lines.map((line, index) => (
            <Text
              key={`${index}-${line.text}`}
              color={
                line.kind === "add"
                  ? colors.success
                  : line.kind === "remove"
                    ? colors.error
                    : line.kind === "meta"
                      ? colors.warning
                      : colors.muted
              }
            >
              {line.text}
            </Text>
          ))}
          {preview.omitted > 0 ? (
            <Text dimColor>··· {preview.omitted} more lines</Text>
          ) : null}
        </Box>
      ) : null}
      <Box marginTop={1} paddingLeft={2}>
        <JsonArgList jsonStr={args} colored={settings.coloredToolArgs} />
      </Box>
      <Box marginTop={1} flexDirection="column">
        {actionPrompts.map((prompt) => (
          <Text key={prompt} dimColor>{"  "}{prompt}</Text>
        ))}
      </Box>
    </Box>
  );
}
