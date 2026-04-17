/**
 * Zelda-themed startup banner with triforce art and config summary.
 */

import React from "react";
import { Box, Text } from "ink";
import { symbols, modelColor, modelSymbol } from "../theme/index.js";
import type { AppConfig } from "../ipc/protocol.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { shortenPath } from "../utils/path.js";

interface WelcomeBannerProps {
  config: AppConfig;
}

export function WelcomeBanner({ config }: WelcomeBannerProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const shortWorkspace = shortenPath(config.workspace).replace(/\/src\/hobby\//, "/");
  const romName = config.romPath
    ? config.romPath.split("/").pop() ?? ""
    : "";
  const loadedCount = config.models.filter((m) => m.loaded).length;

  return (
    <Box
      width="100%"
      borderStyle="double"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={1}
      flexDirection="column"
    >
      {/* Title & File Select Header */}
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color={colors.triforce}>{symbols.triforce} SELECT A FILE {symbols.triforce}</Text>
      </Box>

      {/* Save Slot Appearance */}
      <Box borderStyle="bold" borderColor={colors.triforce} paddingX={1} flexDirection="column">
        <Box justifyContent="space-between">
          <Box gap={1}>
            <Text bold color={colors.triforce}>FILE 1</Text>
            <Text color={colors.text}>z3cli-v{config.version}</Text>
          </Box>
          <Box gap={1}>
            <Text color={colors.heartFull}>{symbols.heart.repeat(10)}</Text>
            <Text color={colors.rupeeGreen}>{symbols.rupee} 000</Text>
          </Box>
        </Box>

        <Box gap={1} marginTop={1}>
          <Text dimColor>QUEST:</Text>
          <Text color={colors.nayru}>{shortWorkspace}</Text>
          {romName ? (
            <>
              <Text dimColor>{symbols.dot}</Text>
              <Text color={colors.veran}>{romName}</Text>
            </>
          ) : null}
        </Box>

        <Box gap={1}>
          <Text dimColor>GEAR:</Text>
          <Text color={modelColor(config.activeModel, colors)} bold>
            {modelSymbol(config.activeModel)} {config.activeModel}
          </Text>
          <Text dimColor>({config.mode})</Text>
        </Box>

        <Box gap={1}>
          <Text dimColor>ITEMS:</Text>
          <Text color={colors.oracleTools}>
            {config.servers.length} servers {symbols.dot} {config.toolCount} tools
          </Text>
        </Box>
      </Box>

      <Text> </Text>

      {/* Help hints */}
      <Box justifyContent="center">
        <Text dimColor>
          <Text color={colors.text}>/help</Text> {symbols.dot}{" "}
          <Text color={colors.text}>Ctrl+P</Text> {symbols.dot}{" "}
          <Text color={colors.text}>@file</Text> {symbols.dot}{" "}
          <Text color={colors.text}>!cmd</Text> {symbols.dot}{" "}
          <Text color={colors.text}>Tab</Text> {symbols.dot}{" "}
          <Text color={colors.text}>Esc</Text>
        </Text>
      </Box>
    </Box>
  );
}
