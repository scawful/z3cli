/**
 * Tool permission prompt — shown before each tool execution in non-admin modes.
 * Y/Enter to approve, N/Esc to deny.
 */

import React from "react";
import { Box, Text, useInput } from "ink";
import { colors, symbols, serverColor, serverSymbol } from "../theme/index.js";

interface PermissionDialogProps {
  name: string;
  server: string;
  arguments: string;
  onApprove: () => void;
  onDeny: () => void;
}

const MAX_ARG_WIDTH = 64;

function truncate(s: string): string {
  return s.length > MAX_ARG_WIDTH ? s.slice(0, MAX_ARG_WIDTH - 3) + "..." : s;
}

function ArgList({ jsonStr }: { jsonStr: string }): React.ReactElement | null {
  if (!jsonStr) return null;
  try {
    const obj = JSON.parse(jsonStr) as Record<string, unknown>;
    const entries = Object.entries(obj);
    if (entries.length === 0) return null;
    return (
      <Box flexDirection="column">
        {entries.map(([k, v]) => {
          const val = typeof v === "string" ? v : JSON.stringify(v);
          return (
            <Box key={k} gap={1} paddingLeft={2}>
              <Text color={colors.dim}>{k}:</Text>
              <Text>{truncate(val)}</Text>
            </Box>
          );
        })}
      </Box>
    );
  } catch {
    return <Box paddingLeft={2}><Text dimColor>{truncate(jsonStr)}</Text></Box>;
  }
}

export function PermissionDialog({
  name,
  server,
  arguments: args,
  onApprove,
  onDeny,
}: PermissionDialogProps): React.ReactElement {
  const sc = serverColor(server);

  useInput((input, key) => {
    if (key.return || input === "y" || input === "Y") { onApprove(); return; }
    if (key.escape || input === "n" || input === "N") { onDeny(); return; }
  });

  return (
    <Box borderStyle="round" borderColor={colors.warning} paddingX={1} flexDirection="column">
      <Box gap={1}>
        <Text color={colors.warning}>{symbols.sword}</Text>
        <Text bold color={colors.warning}>Allow tool call?</Text>
      </Box>
      <Box gap={1} paddingLeft={1}>
        <Text color={sc}>{serverSymbol(server)}</Text>
        {server ? <Text dimColor>{server} {symbols.arrow}</Text> : null}
        <Text bold color={sc}>{name}</Text>
      </Box>
      <ArgList jsonStr={args} />
      <Text dimColor>{"  "}Y/Enter allow {symbols.dot} N/Esc deny</Text>
    </Box>
  );
}
