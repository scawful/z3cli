/**
 * Top bar: branding · model · backend · mode · ROM · hearts.
 * Border color reflects routing mode when modeColoredBorder is enabled.
 * Broadcast model list appears as a second row in broadcast mode.
 */

import React from "react";
import { Box, Text } from "ink";
import {
  colors, symbols,
  modelColor, modelSymbol,
  modeColor, heartBar,
} from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { basename } from "../utils/path.js";

interface TitleBarProps {
  version: string;
  backend: string;
  model: string;
  mode: string;
  contextPercent: number;
  romPath: string;
  broadcastModels?: string[];
}

export function TitleBar({
  version, backend, model, mode, contextPercent, romPath, broadcastModels,
}: TitleBarProps): React.ReactElement {
  const { settings } = useSettingsContext();
  const romName = romPath ? basename(romPath) : "";
  const hearts = heartBar(contextPercent, 5);
  const borderColor = settings.modeColoredBorder ? modeColor(mode) : colors.triforce;
  const showBroadcast =
    mode === "broadcast" &&
    settings.showBroadcastModels &&
    (broadcastModels?.length ?? 0) > 0;

  return (
    <Box borderStyle="round" borderColor={borderColor} paddingX={1} flexDirection="column">
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text bold color={colors.triforce}>{symbols.triforce} z3cli</Text>
          <Text dimColor>v{version}</Text>
          <Text dimColor>{symbols.dot}</Text>
          <Text color={modelColor(model)} bold>{modelSymbol(model)} {model}</Text>
          <Text dimColor>{symbols.dot}</Text>
          <Text dimColor>{backend}</Text>
          <Text dimColor>{symbols.dot}</Text>
          <Text color={modeColor(mode)}>{mode}</Text>
          {romName ? (
            <>
              <Text dimColor>{symbols.dot}</Text>
              <Text dimColor>{romName}</Text>
            </>
          ) : null}
        </Box>
        <Box gap={1}>
          <Text color={hearts.color}>{hearts.display}</Text>
          <Text color={hearts.color}>{contextPercent}%</Text>
        </Box>
      </Box>
      {showBroadcast ? (
        <Box gap={1} paddingLeft={1}>
          <Text dimColor>broadcast {symbols.arrow}</Text>
          {broadcastModels!.map((m, i) => (
            <React.Fragment key={m}>
              {i > 0 ? <Text dimColor>+</Text> : null}
              <Text color={modelColor(m)}>{modelSymbol(m)} {m}</Text>
            </React.Fragment>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
