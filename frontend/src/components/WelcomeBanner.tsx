/**
 * Zelda-themed startup banner with triforce art and config summary.
 */

import React from "react";
import { Box, Text } from "ink";
import { WELCOME_HINTS } from "../commands/catalog.js";
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
  const shortRegistry = config.registryPath ? shortenPath(config.registryPath) : "";
  const romName = config.romPath
    ? config.romPath.split("/").pop() ?? ""
    : "";
  const loadedCount = config.models.filter((m) => m.loaded).length;
  const serverCount = config.servers.length;

  return (
    <Box
      width="100%"
      borderStyle="double"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={1}
      flexDirection="column"
    >
      {/* Centered Triforce & Title */}
      <Box flexDirection="column" alignItems="center" marginBottom={1}>
        <Text color={colors.triforce} bold>   ▲   </Text>
        <Text color={colors.triforce} bold>  ▲ ▲  </Text>
        <Text bold color={colors.triforce}>THE LEGEND OF Z3CLI</Text>
        <Text dimColor>A Link to the Backend</Text>
      </Box>

      <Box justifyContent="center" marginBottom={1}>
        <Text color={colors.triforce} dimColor>————— {symbols.triforce} SELECT A FILE {symbols.triforce} —————</Text>
      </Box>

      {/* Save Slot Appearance */}
      <Box borderStyle="bold" borderColor={colors.triforce} paddingX={1} flexDirection="column">
        <Box justifyContent="space-between">
          <Box gap={1}>
            <Text bold color={colors.triforce}>FILE 1</Text>
            <Text color={colors.text}>v{config.version}</Text>
          </Box>
          <Box gap={1}>
            <Text color={colors.accent}>{symbols.pendant.repeat(Math.min(3, serverCount))}</Text>
            <Text color={colors.triforce}>{symbols.crystal.repeat(Math.min(7, loadedCount))}</Text>
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

        {shortRegistry ? (
          <Box gap={1}>
            <Text dimColor>MAP:  </Text>
            <Text color={colors.accent}>{shortRegistry}</Text>
          </Box>
        ) : null}

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
          {WELCOME_HINTS.join(` ${symbols.dot} `)}
        </Text>
      </Box>
    </Box>
  );
}
