/**
 * Bracketed key-hint pill that expands/collapses reasoning blocks.
 * Visual only; Ctrl+R globally toggles `settings.collapseReasoning` from App.tsx.
 */

import React from "react";
import { Text } from "ink";
import { useSettingsContext } from "../contexts/SettingsContext.js";

export function ReasoningToggleButton(): React.ReactElement {
  const { colors, settings } = useSettingsContext();
  const label = settings.collapseReasoning ? "expand" : "collapse";
  return (
    <Text>
      <Text dimColor>[</Text>
      <Text color={colors.triforce} bold>^R</Text>
      <Text dimColor> {label}</Text>
      <Text dimColor>]</Text>
    </Text>
  );
}
