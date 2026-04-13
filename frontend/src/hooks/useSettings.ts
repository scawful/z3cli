/**
 * UI settings — persistent toggles for visual features.
 * Stored at ~/.config/z3cli/ui-settings.json.
 */

import { useState, useCallback } from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

export type UIMode = "chat" | "plan" | "review" | "build" | "admin";

const UI_MODES: readonly UIMode[] = ["chat", "plan", "review", "build", "admin"];

export interface UISettings {
  modeColoredBorder: boolean;     // TitleBar border color reflects routing mode
  toolsIndicator: boolean;        // ⚔ icon shows tools on/off in status bar
  showTimestamps: boolean;        // Show time on assistant messages
  showToolGrouping: boolean;      // Show tool name header on result panels
  coloredToolArgs: boolean;       // Key/value coloring in tool arguments
  showFocusFile: boolean;         // Show active focus file in status bar
  showBroadcastModels: boolean;   // Show broadcast model list in title bar
  uiMode: UIMode;                 // Interaction mode (Shift+Tab to cycle)
}

export const DEFAULT_SETTINGS: UISettings = {
  modeColoredBorder: true,
  toolsIndicator: true,
  showTimestamps: true,
  showToolGrouping: true,
  coloredToolArgs: true,
  showFocusFile: true,
  showBroadcastModels: true,
  uiMode: "chat",
};

const SETTINGS_PATH = path.join(os.homedir(), ".config", "z3cli", "ui-settings.json");

function loadSettings(): UISettings {
  try {
    const raw = fs.readFileSync(SETTINGS_PATH, "utf-8");
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<UISettings>) };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings(s: UISettings): void {
  try {
    fs.mkdirSync(path.dirname(SETTINGS_PATH), { recursive: true });
    fs.writeFileSync(SETTINGS_PATH, JSON.stringify(s, null, 2));
  } catch {
    // silently ignore write errors
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<UISettings>(loadSettings);

  const toggleSetting = useCallback((key: keyof UISettings) => {
    setSettings((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      saveSettings(next);
      return next;
    });
  }, []);

  const setSetting = useCallback((key: keyof UISettings, value: boolean) => {
    setSettings((prev) => {
      const next = { ...prev, [key]: value };
      saveSettings(next);
      return next;
    });
  }, []);

  const resetSettings = useCallback(() => {
    const next = { ...DEFAULT_SETTINGS };
    setSettings(next);
    saveSettings(next);
  }, []);

  const cycleMode = useCallback(() => {
    setSettings((prev) => {
      const idx = UI_MODES.indexOf(prev.uiMode);
      const next = { ...prev, uiMode: UI_MODES[(idx + 1) % UI_MODES.length]! };
      saveSettings(next);
      return next;
    });
  }, []);

  return { settings, toggleSetting, setSetting, resetSettings, cycleMode };
}
