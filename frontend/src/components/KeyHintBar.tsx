/**
 * Persistent keyboard hint footer below the StatusBar.
 *
 * Exists so undiscoverable shortcuts (Ctrl+P palette, Shift+Tab mode cycle)
 * are visible without opening Help. Render-only — no business logic.
 *
 * Visibility is decided upstream via `shouldShowKeyHintBar` so the parent
 * can reserve the matching transcript row from the same source.
 */

import React from "react";
import { Box, Text } from "ink";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";

export interface KeyHint {
  key: string;
  label: string;
}

export const KEYBOARD_LEGEND_ITEMS: readonly KeyHint[] = [
  { key: "[Ctrl+P]", label: "Palette" },
  { key: "[Tab]", label: "Complete" },
  { key: "[Shift+Tab]", label: "Mode" },
] as const;

interface KeyHintBarProps {
  visible: boolean;
}

export function KeyHintBar({ visible }: KeyHintBarProps): React.ReactElement | null {
  const { colors } = useSettingsContext();
  if (!visible) return null;
  return (
    <Box width="100%" paddingX={1}>
      <Box gap={1} flexWrap="wrap">
        {KEYBOARD_LEGEND_ITEMS.map((item, index) => (
          <React.Fragment key={item.key}>
            {index > 0 ? <Text dimColor>{symbols.dot}</Text> : null}
            <Text dimColor>
              <Text color={colors.triforce}>{item.key}</Text> {item.label}
            </Text>
          </React.Fragment>
        ))}
      </Box>
    </Box>
  );
}
