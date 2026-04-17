/**
 * 'Book of Mudora' themed help panel.
 * Categorized commands with double borders and themed symbols.
 */

import React, { useState } from "react";
import { Box, Text, useInput } from "ink";
import { colors, symbols } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";

interface HelpCategory {
  title: string;
  symbol: string;
  commands: { name: string; args: string; desc: string }[];
}

const CATEGORIES: HelpCategory[] = [
  {
    title: "Quest & Navigation",
    symbol: "◎",
    commands: [
      { name: "/help", args: "", desc: "Show this legendary scroll" },
      { name: "/workspace", args: "<path>", desc: "Change your current quest domain" },
      { name: "/sessions", args: "", desc: "Browse your past adventures" },
      { name: "/resume", args: "<name>", desc: "Continue a saved journey" },
      { name: "/save", args: "", desc: "Reveal the path to your current scroll" },
      { name: "/status", args: "", desc: "View the state of the world" },
    ],
  },
  {
    title: "Gear & Magic",
    symbol: "⚔",
    commands: [
      { name: "/model", args: "<name>", desc: "Summon a different Oracle" },
      { name: "/mode", args: "<name>", desc: "Change the flow of wisdom" },
      { name: "/backend", args: "[name]", desc: "Switch the source of power" },
      { name: "/orchestrator", args: "[model]", desc: "Set the high-level planner" },
      { name: "/load", args: "[name]", desc: "Prepare a model in the local forge" },
      { name: "/settings", args: "", desc: "Adjust your UI enhancements" },
    ],
  },
  {
    title: "Items & Tools",
    symbol: "🛡",
    commands: [
      { name: "/tools", args: "<on|off>", desc: "Enable or seal away tools" },
      { name: "/servers", args: "", desc: "List connected tool masters" },
      { name: "/permissions", args: "", desc: "Manage tool usage pacts" },
      { name: "/focus", args: "<path>", desc: "Inscribe a file into focus memory" },
      { name: "/shell", args: "[cmd]", desc: "Invoke the persistent spirit of bash" },
    ],
  },
];

interface HelpPanelProps {
  onClose: () => void;
}

export function HelpPanel({ onClose }: HelpPanelProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const [tabIdx, setTabIdx] = useState(0);

  useInput((input, key) => {
    if (key.escape || input === "q") onClose();
    if (key.leftArrow) setTabIdx((i) => (i > 0 ? i - 1 : CATEGORIES.length - 1));
    if (key.rightArrow) setTabIdx((i) => (i < CATEGORIES.length - 1 ? i + 1 : 0));
  });

  const cat = CATEGORIES[tabIdx]!;

  return (
    <Box
      borderStyle="double"
      borderColor={colors.triforce}
      paddingX={2}
      paddingY={1}
      flexDirection="column"
    >
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color={colors.triforce}>{symbols.triforce} BOOK OF MUDORA {symbols.triforce}</Text>
      </Box>

      {/* Tabs */}
      <Box justifyContent="center" gap={3} marginBottom={1}>
        {CATEGORIES.map((c, i) => (
          <Text key={c.title} color={i === tabIdx ? colors.triforce : colors.dim} bold={i === tabIdx}>
            {c.symbol} {c.title}
          </Text>
        ))}
      </Box>

      {/* Command List */}
      <Box flexDirection="column" height={12}>
        {cat.commands.map((cmd) => (
          <Box key={cmd.name} gap={1}>
            <Text color={colors.triforce} bold>{cmd.name.padEnd(16)}</Text>
            <Text color={colors.accent}>{cmd.args.padEnd(12)}</Text>
            <Text dimColor>{cmd.desc}</Text>
          </Box>
        ))}
      </Box>

      <Text> </Text>
      <Box justifyContent="center">
        <Text dimColor>
          ←→ switch category {symbols.dot} Esc/q close
        </Text>
      </Box>
    </Box>
  );
}
