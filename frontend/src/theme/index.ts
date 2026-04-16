/** Zelda-themed terminal color palette, symbols, and styling. */

import {
  isActionLikeModel,
  isCloudLikeModel,
  isPlanLikeModel,
  isToolLikeModel,
  normalizeModelName,
} from "../utils/models.js";

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

const exactModelColorMap: Record<string, string> = {
  din: colors.din,
  nayru: colors.nayru,
  farore: colors.farore,
  veran: colors.veran,
  majora: colors.majora,
  hylia: colors.hylia,
  oracle: colors.nayru,
  "oracle-fast": colors.oracleTools,
};

const exactModelSymbolMap: Record<string, string> = {
  din: symbols.triforce,
  nayru: symbols.crystal,
  farore: symbols.pendant,
  veran: symbols.crystal,
  majora: symbols.shield,
  hylia: symbols.pendant,
  oracle: symbols.compass,
  "oracle-fast": symbols.sword,
};
const ORACLE_MODE_LEGACY_ALIASES = new Set(["oracle-main", "switchhook"]);

export function modelColor(name: string): string {
  const lowered = normalizeModelName(name);
  if (exactModelColorMap[lowered]) {
    return exactModelColorMap[lowered]!;
  }
  if (ORACLE_MODE_LEGACY_ALIASES.has(lowered)) {
    return colors.nayru;
  }
  if (isPlanLikeModel(lowered)) {
    return colors.nayru;
  }
  if (isActionLikeModel(lowered)) {
    return colors.din;
  }
  if (isToolLikeModel(lowered) || lowered.includes("oracle")) {
    return colors.oracleTools;
  }
  if (isCloudLikeModel(lowered)) {
    return colors.triforce;
  }
  return colors.assistant;
}

export function modelSymbol(name: string): string {
  const lowered = normalizeModelName(name);
  if (exactModelSymbolMap[lowered]) {
    return exactModelSymbolMap[lowered]!;
  }
  if (ORACLE_MODE_LEGACY_ALIASES.has(lowered)) {
    return symbols.compass;
  }
  if (isPlanLikeModel(lowered)) {
    return symbols.compass;
  }
  if (isActionLikeModel(lowered) || isToolLikeModel(lowered)) {
    return symbols.sword;
  }
  if (isCloudLikeModel(lowered)) {
    return symbols.triforce;
  }
  return symbols.triforceSmall;
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
  const normalizedMode = normalizeModelName(mode);
  if (ORACLE_MODE_LEGACY_ALIASES.has(normalizedMode)) {
    return colors.nayru;
  }
  switch (normalizedMode) {
    case "oracle":       return colors.nayru;     // wisdom routes
    case "broadcast":    return colors.farore;    // courage to many
    case "orchestrator": return colors.triforce;  // cloud planner drives
    case "manual":       return colors.dim;       // direct control
    default:             return colors.triforce;
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
