/**
 * React context for UI settings — avoids prop-drilling through
 * TitleBar, StatusBar, MessageBubble, and SettingsPanel.
 *
 * App.tsx owns the state (via useSettings) and provides it here.
 * Children read it via useSettingsContext().
 */

import { createContext, useContext } from "react";
import type { UISettings } from "../hooks/useSettings.js";
import type { AppConfig } from "../ipc/protocol.js";

export interface SettingsContextValue {
  settings: UISettings;
  colors: any; // Dynamic themed colors
  config?: AppConfig | null;
  execCommand?: (cmd: string, args: string[]) => void;
  toggleSetting: (key: keyof UISettings) => void;
  setSetting: (key: keyof UISettings, value: any) => void;
  resetSettings: () => void;
  cycleMode: () => void;
  cycleTheme: () => void;
  cycleThinkingMode: () => void;
  cycleThinkingDetail: () => void;
}

export const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettingsContext(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettingsContext: missing SettingsContext.Provider");
  return ctx;
}
