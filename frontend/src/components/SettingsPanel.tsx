/**
 * Interactive UI settings panel.
 * Arrow keys navigate · Space/Enter toggles · Esc closes.
 * Reads and writes settings via SettingsContext.
 */

import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { colors, symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import type { UISettings } from "../hooks/useSettings.js";

interface SettingItem {
  key: keyof UISettings;
  label: string;
  description: string;
}

const SETTING_ITEMS: SettingItem[] = [
  { key: "modeColoredBorder",   label: "Mode-colored border",   description: "TitleBar border color reflects routing mode" },
  { key: "toolsIndicator",      label: "Tools indicator",       description: `${symbols.sword} icon shows tools on/off in status bar` },
  { key: "showTimestamps",      label: "Message timestamps",    description: "Show time on assistant messages" },
  { key: "showToolGrouping",    label: "Tool result grouping",  description: "Show tool name header on result panels" },
  { key: "coloredToolArgs",     label: "Colored tool args",     description: "Color key/value pairs in tool arguments" },
  { key: "showFocusFile",       label: "Focus file indicator",  description: "Show active focus file in status bar" },
  { key: "showBroadcastModels", label: "Broadcast model list",  description: "Show broadcast models in title bar" },
];

interface SettingsPanelProps {
  onClose: () => void;
}

export function SettingsPanel({ onClose }: SettingsPanelProps): React.ReactElement {
  const { settings, toggleSetting } = useSettingsContext();
  const [index, setIndex] = useState(0);

  useInput((input, key) => {
    if (key.escape || input === "q") { onClose(); return; }
    if (key.upArrow) { setIndex((i) => Math.max(0, i - 1)); return; }
    if (key.downArrow) { setIndex((i) => Math.min(SETTING_ITEMS.length - 1, i + 1)); return; }
    if (key.return || input === " ") {
      const item = SETTING_ITEMS[index];
      if (item) toggleSetting(item.key);
    }
  });

  return (
    <Box
      borderStyle="round"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={0}
      flexDirection="column"
    >
      <Box gap={1}>
        <Text bold color={colors.triforce}>{symbols.triforce}</Text>
        <Text bold color={colors.triforce}>UI Settings</Text>
      </Box>
      <Text> </Text>
      {SETTING_ITEMS.map((item, i) => {
        const isSelected = i === index;
        const isOn = settings[item.key];
        return (
          <Box key={item.key} gap={1}>
            <Text color={isSelected ? colors.triforce : colors.dim}>
              {isSelected ? symbols.arrowRight : " "}
            </Text>
            <Text color={isOn ? colors.success : colors.heartEmpty}>
              {isOn ? symbols.crystal : symbols.pendant}
            </Text>
            <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
              {item.label.padEnd(24)}
            </Text>
            <Text dimColor>{item.description}</Text>
          </Box>
        );
      })}
      <Text> </Text>
      <Text dimColor>{"  "}↑↓ navigate {symbols.dot} Space toggle {symbols.dot} Esc close</Text>
    </Box>
  );
}
