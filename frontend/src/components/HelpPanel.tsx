import React from "react";
import { Box, Text, useInput } from "ink";
import { COMMAND_GROUPS } from "../commands/catalog.js";
import { symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";

interface HelpPanelProps {
  onClose: () => void;
}

export function HelpPanel({ onClose }: HelpPanelProps): React.ReactElement {
  const { colors } = useSettingsContext();

  useInput((input, key) => {
    if (key.escape || input === "q") {
      onClose();
    }
  });

  return (
    <Box borderStyle="double" borderColor={colors.triforce} paddingX={1} paddingY={1} flexDirection="column">
      <Box justifyContent="space-between">
        <Text bold color={colors.triforce}>{symbols.triforce} Book of Mudora</Text>
        <Text dimColor>Esc/q close</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text color={colors.text}>Prompt glyphs: <Text color={colors.nayru}>@file</Text> attach files <Text dimColor>{symbols.dot}</Text> <Text color={colors.accent}>#room:0x45</Text> attach project refs <Text dimColor>{symbols.dot}</Text> <Text color={colors.veran}>!cmd</Text> shell</Text>
        <Text dimColor>Shortcuts: Ctrl+P palette {symbols.dot} Shift+Tab mode cycle</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        {COMMAND_GROUPS.map((group, groupIndex) => (
          <Box key={group.key} flexDirection="column" marginTop={groupIndex === 0 ? 0 : 1}>
            <Text bold color={colors.triforce}>{group.symbol} {group.title}</Text>
            {group.entries.map((entry) => (
              <Box key={entry.name} gap={1}>
                <Text color={colors.triforce}>{entry.name}</Text>
                {entry.args ? <Text color={colors.accent}>{entry.args}</Text> : null}
                <Text dimColor>{entry.description}</Text>
              </Box>
            ))}
          </Box>
        ))}
      </Box>
    </Box>
  );
}
