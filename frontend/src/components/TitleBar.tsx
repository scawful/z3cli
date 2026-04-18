/**
 * Top bar: branding · model · backend · mode · ROM · hearts.
 * Border color reflects routing mode when modeColoredBorder is enabled.
 * Broadcast model list appears as a second row in broadcast mode.
 */

import React from "react";
import { Box, Text } from "ink";
import {
  symbols,
  modelColor, modelSymbol,
  modeColor, heartBar,
} from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { basename } from "../utils/path.js";
import { modelOptInLabel } from "../utils/models.js";

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
  const { settings, colors } = useSettingsContext();
  const pulse = useAnimatedFrame(["1", "0"], 400);
  const isCritical = contextPercent > 80;

  const romName = romPath ? basename(romPath) : "";
  const modelWarning = modelOptInLabel(model);
  const hearts = heartBar(contextPercent, 5, colors);
  const heartColor = (isCritical && pulse === "1") ? colors.text : hearts.color;

  const borderColor = settings.modeColoredBorder ? modeColor(mode, colors) : colors.triforce;
  const showBroadcast =
    mode === "broadcast" &&
    settings.showBroadcastModels &&
    (broadcastModels?.length ?? 0) > 0;

  return (
    <Box width="100%" borderStyle="round" borderColor={borderColor} paddingX={1} flexDirection="column">
      <Box width="100%" justifyContent="space-between">
        <Box gap={1}>
          <Text bold color={colors.triforce}>{symbols.triforce} z3cli</Text>
          <Text dimColor>v{version}</Text>
          <Text dimColor>{symbols.dot}</Text>
          <Text color={modelColor(model, colors)} bold>{modelSymbol(model)} {model}</Text>
          {modelWarning ? <Text color={colors.warning}>{modelWarning}</Text> : null}
          <Text dimColor>{symbols.dot}</Text>
          <Text dimColor>{backend}</Text>
          <Text dimColor>{symbols.dot}</Text>
          <Text color={modeColor(mode, colors)}>{mode}</Text>
          {romName ? (
            <>
              <Text dimColor>{symbols.dot}</Text>
              <Text dimColor>{romName}</Text>
            </>
          ) : null}
        </Box>
        <Box gap={1}>
          <Text dimColor>ctx</Text>
          <Text color={heartColor}>{hearts.display}</Text>
          <Text color={heartColor}>{contextPercent}%</Text>
        </Box>
      </Box>
      {showBroadcast ? (
        <Box gap={1} paddingLeft={1}>
          <Text dimColor>broadcast {symbols.arrow}</Text>
          {broadcastModels!.map((m, i) => (
            <React.Fragment key={`${m}-${i}`}>
              {i > 0 ? <Text dimColor>+</Text> : null}
              <Text color={modelColor(m, colors)}>{modelSymbol(m)} {m}</Text>
            </React.Fragment>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
