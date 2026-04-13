/**
 * Zelda-themed startup banner with triforce art and config summary.
 */

import React from "react";
import { Box, Text } from "ink";
import { colors, symbols, modelColor, modelSymbol } from "../theme/index.js";
import type { AppConfig } from "../ipc/protocol.js";

interface WelcomeBannerProps {
  config: AppConfig;
}

export function WelcomeBanner({ config }: WelcomeBannerProps): React.ReactElement {
  const shortWorkspace = config.workspace
    .replace(/^\/Users\/[^/]+/, "~")
    .replace(/\/src\/hobby\//, "/");
  const romName = config.romPath
    ? config.romPath.split("/").pop() ?? ""
    : "";
  const loadedCount = config.models.filter((m) => m.loaded).length;

  return (
    <Box
      borderStyle="round"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={0}
      flexDirection="column"
    >
      {/* Triforce + title */}
      <Box flexDirection="column" alignItems="center">
        <Text bold color={colors.triforce}>
          {"    "}{symbols.triforce}
        </Text>
        <Text bold color={colors.triforce}>
          {"   "}{symbols.triforce} {symbols.triforce}
        </Text>
        <Text> </Text>
        <Box gap={1}>
          <Text bold color={colors.triforce}>z3cli</Text>
          <Text dimColor>v{config.version}</Text>
        </Box>
        <Text dimColor>Oracle of Secrets Development Kit</Text>
      </Box>

      <Text> </Text>

      {/* Config */}
      <Box gap={1} paddingLeft={2}>
        <Text>{shortWorkspace}</Text>
        {romName ? (
          <>
            <Text dimColor>{symbols.dot}</Text>
            <Text>{romName}</Text>
          </>
        ) : null}
        <Text dimColor>{symbols.dot}</Text>
        <Text dimColor>{config.backend}</Text>
        <Text dimColor>{symbols.dot}</Text>
        <Text dimColor>{config.mode}</Text>
      </Box>
      {config.servers.length > 0 ? (
        <Box gap={1} paddingLeft={2}>
          <Text dimColor>
            {config.servers.length} servers {symbols.dot} {config.toolCount} tools
          </Text>
        </Box>
      ) : null}

      {/* Active model */}
      <Box gap={1} paddingLeft={2}>
        <Text color={modelColor(config.activeModel)} bold>
          {modelSymbol(config.activeModel)} {config.activeModel}
        </Text>
        <Text dimColor>active</Text>
        {loadedCount > 1 ? (
          <>
            <Text dimColor>{symbols.dot}</Text>
            <Text dimColor>{loadedCount} loaded</Text>
          </>
        ) : null}
      </Box>

      <Text> </Text>

      {/* Help hints */}
      <Text dimColor>
        {"  "}<Text color={colors.text}>/help</Text> commands {symbols.dot}{" "}
        <Text color={colors.text}>Tab</Text> complete {symbols.dot}{" "}
        <Text color={colors.text}>Esc</Text> cancel
      </Text>
    </Box>
  );
}
