/**
 * Zelda-themed startup banner: handlaid triforce sigil, FILE 1 save slot,
 * and a brief PRESS START boot pulse that fades to a static hint footer.
 *
 * Border vocabulary: `double` — modal-style overlay shown until first prompt.
 */

import React, { useEffect, useState } from "react";
import { Box, Text } from "ink";
import { WELCOME_HINTS } from "../commands/catalog.js";
import { symbols, modelColor, modelSymbol } from "../theme/index.js";
import type { AppConfig } from "../ipc/protocol.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { shortenPath } from "../utils/path.js";
import { formatModelMemory } from "../utils/models.js";

interface WelcomeBannerProps {
  config: AppConfig;
}

const SIGIL_LINES = [
  "         ▲         ",
  "        ▲ ▲        ",
  "       ▲▲▲▲▲       ",
  "      ▲▲▲ ▲▲▲      ",
  "     ▲▲▲▲▲▲▲▲▲     ",
] as const;

const PRESS_START_PULSE_MS = 3000;
const PRESS_START_TEXT = "▸ PRESS START ◂";
const PRESS_START_FRAMES = [PRESS_START_TEXT, " ".repeat(PRESS_START_TEXT.length)];

function PressStartPulse({ color }: { color: string }): React.ReactElement {
  const [pulsing, setPulsing] = useState(true);
  const frame = useAnimatedFrame(PRESS_START_FRAMES, 600);
  useEffect(() => {
    const timer = setTimeout(() => setPulsing(false), PRESS_START_PULSE_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <Text bold color={color} dimColor={!pulsing}>
      {pulsing ? frame : PRESS_START_TEXT}
    </Text>
  );
}

// Spread word into NES-style spaced caps: "QUEST" → "Q U E S T".
function spacedCaps(word: string): string {
  return word.split("").join(" ");
}

export function WelcomeBanner({ config }: WelcomeBannerProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const shortWorkspace = shortenPath(config.workspace).replace(/\/src\/hobby\//, "/");
  const shortRegistry = config.registryPath ? shortenPath(config.registryPath) : "";
  const romName = config.romPath
    ? config.romPath.split("/").pop() ?? ""
    : "";
  const loadedCount = config.loadedModelCount ?? config.models.filter((m) => m.loaded).length;
  const loadedMemory = formatModelMemory(config.loadedModelMemoryBytes);
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
      {/* Triforce sigil + title + boot pulse */}
      <Box flexDirection="column" alignItems="center" marginBottom={1}>
        {SIGIL_LINES.map((line, index) => (
          <Text key={index} bold color={colors.triforce}>{line}</Text>
        ))}
        <Box marginTop={1}>
          <Text bold color={colors.triforce}>THE LEGEND OF Z3CLI</Text>
        </Box>
        <Text dimColor>A Link to the Backend</Text>
        <Box marginTop={1}>
          <PressStartPulse color={colors.accent} />
        </Box>
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
          <Text dimColor>{spacedCaps("QUEST")}</Text>
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
            <Text dimColor>{spacedCaps("MAP")}  </Text>
            <Text color={colors.accent}>{shortRegistry}</Text>
          </Box>
        ) : null}

        <Box gap={1}>
          <Text dimColor>{spacedCaps("GEAR")}</Text>
          <Text color={modelColor(config.activeModel, colors)} bold>
            {modelSymbol(config.activeModel)} {config.activeModel}
          </Text>
          <Text dimColor>({config.mode})</Text>
        </Box>

        <Box gap={1}>
          <Text dimColor>{spacedCaps("ITEMS")}</Text>
          <Text color={colors.oracleTools}>
            {config.servers.length} servers {symbols.dot} {config.toolCount} tools
          </Text>
        </Box>

        <Box gap={1}>
          <Text dimColor>{spacedCaps("LOAD")}</Text>
          <Text color={colors.success}>
            {loadedCount} live{loadedMemory ? ` ${symbols.dot} ${loadedMemory}` : ""}
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
