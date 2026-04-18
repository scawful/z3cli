/**
 * UI settings — persistent toggles for visual features.
 * Stored at ~/.config/z3cli/ui-settings.json.
 */

import { useState, useCallback } from "react";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

export type UIMode = "chat" | "plan" | "review" | "build" | "admin";
export type UITheme = "gold" | "green" | "red" | "blue";
export type ShowThinkingMode = "off" | "streamed-only" | "transcript";
export type ThinkingDetailMode = "preview" | "full";

export const UI_MODES: readonly UIMode[] = ["chat", "plan", "review", "build", "admin"];
export const UI_THEMES: readonly UITheme[] = ["gold", "green", "red", "blue"];
export const UI_THINKING_MODES: readonly ShowThinkingMode[] = ["off", "streamed-only", "transcript"];
export const UI_THINKING_DETAILS: readonly ThinkingDetailMode[] = ["preview", "full"];

export interface UISettings {
  modeColoredBorder: boolean;     // TitleBar border color reflects routing mode
  toolsIndicator: boolean;        // ⚔ icon shows tools on/off in status bar
  showTimestamps: boolean;        // Show time on assistant messages
  showToolGrouping: boolean;      // Show tool name header on result panels
  coloredToolArgs: boolean;       // Key/value coloring in tool arguments
  showFocusFile: boolean;         // Show active focus file in status bar
  showBroadcastModels: boolean;   // Show broadcast model list in title bar
  showDiagnostics: boolean;       // Expand telemetry/diagnostics card in context panel
  uiMode: UIMode;                 // Interaction mode (Shift+Tab to cycle)
  theme: UITheme;                 // UI color theme
  showThinking: ShowThinkingMode; // Where model reasoning is visible
  thinkingDetail: ThinkingDetailMode; // Whether reasoning blocks are previewed or fully expanded
  collapseReasoning: boolean;     // Show reasoning blocks as one-line summaries by default
  transcriptShowMessages: boolean; // Show user/system/assistant message bodies in transcript
  transcriptShowReasoning: boolean; // Show assistant/subagent reasoning traces in transcript
  transcriptShowTools: boolean;   // Show tool calls and tool results in transcript
  transcriptShowSubagents: boolean; // Show the subagent side-quest panel in transcript
}

export const DEFAULT_SETTINGS: UISettings = {
  modeColoredBorder: true,
  toolsIndicator: true,
  showTimestamps: true,
  showToolGrouping: true,
  coloredToolArgs: true,
  showFocusFile: true,
  showBroadcastModels: true,
  showDiagnostics: false,
  uiMode: "chat",
  theme: "gold",
  showThinking: "transcript",
  thinkingDetail: "preview",
  collapseReasoning: true,
  transcriptShowMessages: true,
  transcriptShowReasoning: true,
  transcriptShowTools: true,
  transcriptShowSubagents: true,
};

const SETTINGS_PATH = path.join(os.homedir(), ".config", "z3cli", "ui-settings.json");

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isUIMode(value: unknown): value is UIMode {
  return typeof value === "string" && UI_MODES.includes(value as UIMode);
}

function isUITheme(value: unknown): value is UITheme {
  return typeof value === "string" && UI_THEMES.includes(value as UITheme);
}

function isShowThinkingMode(value: unknown): value is ShowThinkingMode {
  return typeof value === "string" && UI_THINKING_MODES.includes(value as ShowThinkingMode);
}

function isThinkingDetailMode(value: unknown): value is ThinkingDetailMode {
  return typeof value === "string" && UI_THINKING_DETAILS.includes(value as ThinkingDetailMode);
}

export function normalizeSettings(raw: Partial<UISettings> | null | undefined): UISettings {
  const merged = { ...DEFAULT_SETTINGS, ...(raw ?? {}) };
  return {
    modeColoredBorder: isBoolean(merged.modeColoredBorder)
      ? merged.modeColoredBorder
      : DEFAULT_SETTINGS.modeColoredBorder,
    toolsIndicator: isBoolean(merged.toolsIndicator)
      ? merged.toolsIndicator
      : DEFAULT_SETTINGS.toolsIndicator,
    showTimestamps: isBoolean(merged.showTimestamps)
      ? merged.showTimestamps
      : DEFAULT_SETTINGS.showTimestamps,
    showToolGrouping: isBoolean(merged.showToolGrouping)
      ? merged.showToolGrouping
      : DEFAULT_SETTINGS.showToolGrouping,
    coloredToolArgs: isBoolean(merged.coloredToolArgs)
      ? merged.coloredToolArgs
      : DEFAULT_SETTINGS.coloredToolArgs,
    showFocusFile: isBoolean(merged.showFocusFile)
      ? merged.showFocusFile
      : DEFAULT_SETTINGS.showFocusFile,
    showBroadcastModels: isBoolean(merged.showBroadcastModels)
      ? merged.showBroadcastModels
      : DEFAULT_SETTINGS.showBroadcastModels,
    showDiagnostics: isBoolean(merged.showDiagnostics)
      ? merged.showDiagnostics
      : DEFAULT_SETTINGS.showDiagnostics,
    uiMode: isUIMode(merged.uiMode) ? merged.uiMode : DEFAULT_SETTINGS.uiMode,
    theme: isUITheme(merged.theme) ? merged.theme : DEFAULT_SETTINGS.theme,
    showThinking: isShowThinkingMode(merged.showThinking)
      ? merged.showThinking
      : DEFAULT_SETTINGS.showThinking,
    thinkingDetail: isThinkingDetailMode(merged.thinkingDetail)
      ? merged.thinkingDetail
      : DEFAULT_SETTINGS.thinkingDetail,
    collapseReasoning: isBoolean(merged.collapseReasoning)
      ? merged.collapseReasoning
      : DEFAULT_SETTINGS.collapseReasoning,
    transcriptShowMessages: isBoolean(merged.transcriptShowMessages)
      ? merged.transcriptShowMessages
      : DEFAULT_SETTINGS.transcriptShowMessages,
    transcriptShowReasoning: isBoolean(merged.transcriptShowReasoning)
      ? merged.transcriptShowReasoning
      : DEFAULT_SETTINGS.transcriptShowReasoning,
    transcriptShowTools: isBoolean(merged.transcriptShowTools)
      ? merged.transcriptShowTools
      : DEFAULT_SETTINGS.transcriptShowTools,
    transcriptShowSubagents: isBoolean(merged.transcriptShowSubagents)
      ? merged.transcriptShowSubagents
      : DEFAULT_SETTINGS.transcriptShowSubagents,
  };
}

function loadSettings(): UISettings {
  try {
    const raw = fs.readFileSync(SETTINGS_PATH, "utf-8");
    return normalizeSettings(JSON.parse(raw) as Partial<UISettings>);
  } catch {
    return normalizeSettings(null);
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
      if (typeof prev[key] !== "boolean") {
        return prev;
      }
      const next = normalizeSettings({ ...prev, [key]: !prev[key] } as UISettings);
      saveSettings(next);
      return next;
    });
  }, []);

  const setSetting = useCallback((key: keyof UISettings, value: any) => {
    setSettings((prev) => {
      const next = normalizeSettings({ ...prev, [key]: value } as UISettings);
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

  const cycleTheme = useCallback(() => {
    setSettings((prev) => {
      const idx = UI_THEMES.indexOf(prev.theme);
      const next = { ...prev, theme: UI_THEMES[(idx + 1) % UI_THEMES.length]! };
      saveSettings(next);
      return next;
    });
  }, []);

  const cycleThinkingMode = useCallback(() => {
    setSettings((prev) => {
      const idx = UI_THINKING_MODES.indexOf(prev.showThinking);
      const next = { ...prev, showThinking: UI_THINKING_MODES[(idx + 1) % UI_THINKING_MODES.length]! };
      saveSettings(next);
      return next;
    });
  }, []);

  const cycleThinkingDetail = useCallback(() => {
    setSettings((prev) => {
      const idx = UI_THINKING_DETAILS.indexOf(prev.thinkingDetail);
      const next = { ...prev, thinkingDetail: UI_THINKING_DETAILS[(idx + 1) % UI_THINKING_DETAILS.length]! };
      saveSettings(next);
      return next;
    });
  }, []);

  return {
    settings,
    toggleSetting,
    setSetting,
    resetSettings,
    cycleMode,
    cycleTheme,
    cycleThinkingMode,
    cycleThinkingDetail,
  };
}
