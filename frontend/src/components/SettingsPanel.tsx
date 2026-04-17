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

type TabType = "Gear" | "Items" | "Map";

const TABS: { type: TabType; label: string; symbol: string }[] = [
  { type: "Gear", label: "Gear", symbol: "⚔" },
  { type: "Items", label: "Items", symbol: "🛡" },
  { type: "Map", label: "Map", symbol: "◎" },
];

const SETTINGS_BY_TAB: Record<TabType, SettingItem[]> = {
  Gear: [
    { key: "showTimestamps", label: "Message Timestamps", description: "Show time on assistant messages" },
    { key: "modeColoredBorder", label: "Mode-Colored Border", description: "TitleBar border reflects routing mode" },
  ],
  Items: [
    { key: "toolsIndicator", label: "Tools Indicator", description: `${symbols.sword} icon shows tools on/off` },
    { key: "showToolGrouping", label: "Tool Result Grouping", description: "Show tool name header on result panels" },
    { key: "coloredToolArgs", label: "Colored Tool Args", description: "Color key/value pairs in tool arguments" },
    { key: "showBroadcastModels", label: "Broadcast Model List", description: "Show broadcast models in title bar" },
  ],
  Map: [
    { key: "showFocusFile", label: "Focus File Indicator", description: "Show active focus file in status bar" },
  ],
};

interface SettingsPanelProps {
  onClose: () => void;
}

export function SettingsPanel({ onClose }: SettingsPanelProps): React.ReactElement {
  const { settings, colors, toggleSetting, cycleTheme } = useSettingsContext();
  const [activeTabIdx, setActiveTabIdx] = useState(0);
  const [index, setIndex] = useState(0);

  const activeTab = TABS[activeTabIdx]!;
  const tabItems = [
    ...SETTINGS_BY_TAB[activeTab.type],
    ...(activeTab.type === "Gear" ? [{ key: "theme", label: "UI Theme", description: `Current: ${settings.theme}` }] : []),
  ];

  useInput((input, key) => {
    if (key.escape || input === "q") { onClose(); return; }

    // Tab switching
    if (key.leftArrow) {
      setActiveTabIdx((i) => (i > 0 ? i - 1 : TABS.length - 1));
      setIndex(0);
      return;
    }
    if (key.rightArrow) {
      setActiveTabIdx((i) => (i < TABS.length - 1 ? i + 1 : 0));
      setIndex(0);
      return;
    }

    // Item navigation
    if (key.upArrow) { setIndex((i) => Math.max(0, i - 1)); return; }
    if (key.downArrow) { setIndex((i) => Math.min(tabItems.length - 1, i + 1)); return; }

    // Toggle/Cycle
    if (key.return || input === "\r" || input === "\n" || input === " ") {
      const item = tabItems[index];
      if (!item) return;
      if (item.key === "theme") {
        cycleTheme();
      } else {
        toggleSetting(item.key as keyof UISettings);
      }
    }
  });

  return (
    <Box
      borderStyle="double"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={1}
      flexDirection="column"
    >
      {/* Tab Bar */}
      <Box justifyContent="center" gap={4} marginBottom={1}>
        {TABS.map((t, i) => {
          const isSelected = i === activeTabIdx;
          return (
            <Box key={t.type} gap={1}>
              <Text color={isSelected ? colors.triforce : colors.dim} bold={isSelected}>
                {t.symbol} {t.label}
              </Text>
            </Box>
          );
        })}
      </Box>

      {/* Items List */}
      <Box flexDirection="column" height={10}>
        {tabItems.map((item, i) => {
          const isSelected = i === index;
          const isOn = item.key === "theme" ? true : (settings as any)[item.key];
          const isTheme = item.key === "theme";

          return (
            <Box key={item.key} gap={1}>
              <Text color={isSelected ? colors.triforce : colors.dim}>
                {isSelected ? symbols.arrowRight : " "}
              </Text>
              <Box width={3}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isTheme ? `[${symbols.crystal}]` : (isOn ? "[⚔]" : "[ ]")}
                </Text>
              </Box>
              <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                {item.label.padEnd(24)}
              </Text>
              <Text color={isSelected ? colors.accent : colors.muted}>{item.description}</Text>
            </Box>
          );
        })}
      </Box>

      <Text> </Text>
      <Box justifyContent="center">
        <Text dimColor>
          ←→ switch tab {symbols.dot} ↑↓ navigate {symbols.dot} Space toggle {symbols.dot} Esc close
        </Text>
      </Box>
    </Box>
  );
}
