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
  key: keyof UISettings | "theme" | "showThinking" | "thinkingDetail" | "backend_tools" | "backend_write" | "backend_verify";
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
  { type: "Items", label: "Inventory", symbol: "🛡" },
  { type: "Map", label: "Map", symbol: "◎" },
];

const SETTINGS_BY_TAB: Record<TabType, SettingItem[]> = {
  Gear: [
    { key: "showTimestamps", label: "Message Timestamps", description: "Show time on assistant messages" },
    { key: "modeColoredBorder", label: "Mode-Colored Border", description: "TitleBar border reflects routing mode" },
    { key: "theme", label: "UI Theme", description: "Cycle visual color palette" },
    { key: "showThinking", label: "Reasoning Visibility", description: "Choose where model reasoning appears" },
    { key: "thinkingDetail", label: "Reasoning Detail", description: "Toggle truncated previews versus full reasoning" },
  ],
  Items: [
    { key: "backend_tools", label: "Master Sword (Tools)", description: "Toggle all tool bridge access" },
    { key: "backend_write", label: "Hammer (Write Access)", description: "Toggle write/edit tool capability" },
    { key: "backend_verify", label: "Shield (Auto-Verify)", description: "Toggle automatic post-edit verification" },
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
  const {
    settings,
    colors,
    config,
    execCommand,
    toggleSetting,
    cycleTheme,
    cycleThinkingMode,
    cycleThinkingDetail,
  } = useSettingsContext();
  const [activeTabIdx, setActiveTabIdx] = useState(0);
  const [index, setIndex] = useState(0);

  const activeTab = TABS[activeTabIdx]!;
  const tabItems = SETTINGS_BY_TAB[activeTab.type];

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
      } else if (item.key === "showThinking") {
        cycleThinkingMode();
      } else if (item.key === "thinkingDetail") {
        cycleThinkingDetail();
      } else if (item.key === "backend_tools") {
        execCommand?.("/tools", [config?.toolsEnabled ? "off" : "on"]);
      } else if (item.key === "backend_write") {
        execCommand?.("/tools-write", [config?.toolsWrite ? "off" : "on"]);
      } else if (item.key === "backend_verify") {
        execCommand?.("/verify-hooks", [config?.verifyHooks ? "off" : "on"]);
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
      <Box flexDirection="column" height={12}>
        {tabItems.map((item, i) => {
          const isSelected = i === index;

          let isOn = false;
          let valueLabel = "";
          if (item.key === "theme") {
            isOn = true;
            valueLabel = settings.theme;
          } else if (item.key === "showThinking") {
            isOn = true;
            valueLabel = settings.showThinking;
          } else if (item.key === "thinkingDetail") {
            isOn = true;
            valueLabel = settings.thinkingDetail;
          } else if (item.key === "backend_tools") {
            isOn = !!config?.toolsEnabled;
          } else if (item.key === "backend_write") {
            isOn = !!config?.toolsWrite;
          } else if (item.key === "backend_verify") {
            isOn = !!config?.verifyHooks;
          } else {
            isOn = (settings as any)[item.key];
          }

          const isEnum = item.key === "theme" || item.key === "showThinking" || item.key === "thinkingDetail";

          return (
            <Box key={item.key} gap={1}>
              <Text color={isSelected ? colors.triforce : colors.dim}>
                {isSelected ? symbols.arrowRight : " "}
              </Text>
              <Box width={3}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isEnum ? `[${symbols.crystal}]` : (isOn ? "[⚔]" : "[ ]")}
                </Text>
              </Box>
              <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                {item.label.padEnd(24)}
              </Text>
              <Text color={isSelected ? colors.accent : colors.muted}>{item.description}</Text>
              {valueLabel ? <Text dimColor>· {valueLabel}</Text> : null}
            </Box>
          );
        })}
      </Box>

      <Text> </Text>
      <Box justifyContent="center">
        <Text dimColor>
          ←→ switch tab {symbols.dot} ↑↓ navigate {symbols.dot} Space toggle or cycle
        </Text>
      </Box>
    </Box>
  );
}
