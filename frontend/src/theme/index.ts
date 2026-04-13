/** Zelda-themed terminal color palette, symbols, and styling. */

// ---------------------------------------------------------------------------
// Oracle Goddess palette
// ---------------------------------------------------------------------------

export const colors = {
  // The three goddesses
  din: "#EF4444",        // red — power, optimization
  nayru: "#3B82F6",      // blue — wisdom, explanation
  farore: "#22C55E",     // green — courage, autocomplete

  // Oracle pantheon
  veran: "#8B5CF6",      // purple — sorceress of shadows
  majora: "#F97316",     // orange — mask of chaos
  hylia: "#EC4899",      // pink — golden goddess
  oracleTools: "#FBBF24", // amber — tool-calling

  // Triforce gold
  triforce: "#FFD700",

  // UI chrome
  border: "#374151",
  borderActive: "#FFD700",  // triforce gold when active
  accent: "#FFD700",
  success: "#22C55E",
  error: "#EF4444",
  warning: "#F59E0B",
  dim: "#6B7280",
  text: "#E5E7EB",
  muted: "#9CA3AF",

  // Roles
  user: "#5EEAD4",
  assistant: "#A78BFA",
  system: "#6B7280",
  tool: "#FBBF24",

  // Hearts (context)
  heartFull: "#EF4444",
  heartLow: "#F59E0B",
  heartEmpty: "#4B5563",

  // Rupees (tokens)
  rupeeGreen: "#22C55E",
  rupeeBlue: "#3B82F6",
  rupeeRed: "#EF4444",

  // Hex addresses
  address: "#FFD700",
} as const;

// ---------------------------------------------------------------------------
// Zelda symbols
// ---------------------------------------------------------------------------

export const symbols = {
  triforce: "▲",
  triforceSmall: "△",
  crystal: "◆",
  pendant: "◇",
  heart: "♥",
  heartEmpty: "♡",
  sword: "⚔",
  arrow: "→",
  arrowRight: "❯",
  rupee: "◆",
  compass: "◎",
  shield: "◈",
  spinner: ["◜", "◠", "◝", "◞", "◡", "◟"],
  dot: "·",
  bar: "│",
  thinking: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
} as const;

// ---------------------------------------------------------------------------
// Model theming
// ---------------------------------------------------------------------------

const modelColorMap: Record<string, string> = {
  din: colors.din,
  nayru: colors.nayru,
  farore: colors.farore,
  veran: colors.veran,
  majora: colors.majora,
  hylia: colors.hylia,
  "oracle-tools": colors.oracleTools,
  "oracle-fast": colors.oracleTools,
  "switchhook-plan": colors.nayru,
  "switchhook-act": colors.din,
};

const modelSymbolMap: Record<string, string> = {
  din: symbols.triforce,
  nayru: symbols.crystal,
  farore: symbols.pendant,
  veran: symbols.crystal,
  majora: symbols.shield,
  hylia: symbols.pendant,
  "oracle-tools": symbols.sword,
  "oracle-fast": symbols.sword,
  "switchhook-plan": symbols.compass,
  "switchhook-act": symbols.sword,
};

export function modelColor(name: string): string {
  return modelColorMap[name] ?? colors.assistant;
}

export function modelSymbol(name: string): string {
  return modelSymbolMap[name] ?? symbols.triforceSmall;
}

// ---------------------------------------------------------------------------
// Server theming — each MCP server gets a goddess-aligned color and symbol
// ---------------------------------------------------------------------------

const serverColorMap: Record<string, string> = {
  "book-of-mudora": colors.nayru,      // wisdom — code search
  "hyrule-historian": colors.farore,    // courage — lore/data
  "yaze-editor": colors.din,           // power — ROM editing
  "mesen2-oos": colors.veran,          // dark magic — debugging
  "afs": colors.oracleTools,           // amber — file system
};

const serverSymbolMap: Record<string, string> = {
  "book-of-mudora": symbols.pendant,   // wisdom pendant
  "hyrule-historian": symbols.compass,  // historical records
  "yaze-editor": symbols.sword,        // editing power
  "mesen2-oos": symbols.crystal,       // debug crystal
  "afs": symbols.triforceSmall,        // general
};

// ---------------------------------------------------------------------------
// Mode theming — routing mode gets a goddess-aligned color
// ---------------------------------------------------------------------------

export function modeColor(mode: string): string {
  switch (mode) {
    case "oracle":     return colors.nayru;      // wisdom routes
    case "broadcast":  return colors.farore;     // courage to many
    case "switchhook": return colors.din;        // power splits
    case "manual":     return colors.dim;        // direct control
    default:           return colors.triforce;
  }
}

export function serverColor(name: string): string {
  return serverColorMap[name] ?? colors.tool;
}

export function serverSymbol(name: string): string {
  return serverSymbolMap[name] ?? symbols.triforceSmall;
}

// ---------------------------------------------------------------------------
// Heart container — context window as Zelda health
// ---------------------------------------------------------------------------

export function heartBar(
  percent: number,
  maxHearts: number = 10,
): { display: string; color: string } {
  // Hearts represent remaining capacity (100% used = 0 hearts)
  const remaining = Math.round(((100 - percent) / 100) * maxHearts);
  const full = Math.max(0, Math.min(maxHearts, remaining));
  const empty = maxHearts - full;
  const display = symbols.heart.repeat(full) + symbols.heartEmpty.repeat(empty);

  const color =
    full <= 2 ? colors.error : full <= 4 ? colors.heartLow : colors.heartFull;

  return { display, color };
}

// ---------------------------------------------------------------------------
// Rupee — token counter formatting
// ---------------------------------------------------------------------------

export function formatTokens(count: number): { text: string; color: string } {
  if (count === 0) return { text: "", color: colors.dim };
  const num = count > 1000 ? `${(count / 1000).toFixed(1)}k` : `${count}`;
  const color =
    count > 10000
      ? colors.rupeeRed
      : count > 3000
        ? colors.rupeeBlue
        : colors.rupeeGreen;
  return { text: `${symbols.rupee} ${num}`, color };
}

