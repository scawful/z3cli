/** Zelda-themed terminal color palette, symbols, and styling. */

import {
  isActionLikeModel,
  isCloudLikeModel,
  isPlanLikeModel,
  isToolLikeModel,
  normalizeModelName,
} from "../utils/models.js";

// ---------------------------------------------------------------------------
// Palettes
// ---------------------------------------------------------------------------

const palettes = {
  gold: {
    primary: "#FFD700",
    accent: "#FFD700",
  },
  green: {
    primary: "#22C55E",
    accent: "#22C55E",
  },
  red: {
    primary: "#EF4444",
    accent: "#EF4444",
  },
  blue: {
    primary: "#3B82F6",
    accent: "#3B82F6",
  },
};

export function getThemeColors(theme: string = "gold") {
  const p = (palettes as any)[theme] || palettes.gold;
  return {
    // The three goddesses
    din: "#EF4444",        // red — power, optimization
    nayru: "#3B82F6",      // blue — wisdom, explanation
    farore: "#22C55E",     // green — courage, autocomplete

    // Oracle pantheon
    veran: "#8B5CF6",      // purple — sorceress of shadows
    majora: "#F97316",     // orange — mask of chaos
    hylia: "#EC4899",      // pink — golden goddess
    oracleTools: "#FBBF24", // amber — tool-calling

    // Theme primary
    triforce: p.primary,
    accent: p.accent,

    // UI chrome
    border: p.primary,
    borderActive: p.primary,
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
    address: p.primary,
  };
}

// Default export for backward compatibility
export const colors = getThemeColors("gold");

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
  spinner: ["◈", "◇", "◈", "◆"],
  dot: "·",
  bar: "│",
  thinking: ["✧", "✦", "✧", " "],
} as const;

// ---------------------------------------------------------------------------
// Item/Tool symbols
// ---------------------------------------------------------------------------

const toolSymbolMap: Record<string, string> = {
  // Common tool mappings
  read_file: "📖",
  write_file: "🔨",
  replace: "⚔",
  grep_search: "◎",
  glob: "◎",
  list_directory: "◎",
  web_fetch: "🎵",
  run_shell_command: "📜",
  ask_user: "💬",
  enter_plan_mode: "🗺",
  exit_plan_mode: "▲",
};

/** Map tool name to Zelda item icons. */
export function toolSymbol(name: string): string {
  const lowered = name.toLowerCase();
  for (const [key, symbol] of Object.entries(toolSymbolMap)) {
    if (lowered.includes(key)) return symbol;
  }
  return symbols.shield;
}

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

export function modelColor(name: string, c: any = colors): string {
  const exactModelColorMap: Record<string, string> = {
    din: c.din,
    nayru: c.nayru,
    farore: c.farore,
    veran: c.veran,
    majora: c.majora,
    hylia: c.hylia,
    oracle: c.nayru,
    "oracle-fast": c.oracleTools,
  };

  const lowered = normalizeModelName(name);
  if (exactModelColorMap[lowered]) {
    return exactModelColorMap[lowered]!;
  }
  if (ORACLE_MODE_LEGACY_ALIASES.has(lowered)) {
    return c.nayru;
  }
  if (isPlanLikeModel(lowered)) {
    return c.nayru;
  }
  if (isActionLikeModel(lowered)) {
    return c.din;
  }
  if (isToolLikeModel(lowered) || lowered.includes("oracle")) {
    return c.oracleTools;
  }
  if (isCloudLikeModel(lowered)) {
    return c.triforce;
  }
  return c.assistant;
}

export function modelSymbol(name: string): string {
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

export function serverColor(name: string, c: any = colors): string {
  const serverColorMap: Record<string, string> = {
    "book-of-mudora": c.nayru,      // wisdom — code search
    "hyrule-historian": c.farore,    // courage — lore/data
    "yaze-editor": c.din,           // power — ROM editing
    "mesen2-oos": c.veran,          // dark magic — debugging
    "afs": c.oracleTools,           // amber — file system
  };
  return serverColorMap[name] ?? c.tool;
}

export function serverSymbol(name: string): string {
  const serverSymbolMap: Record<string, string> = {
    "book-of-mudora": symbols.pendant,   // wisdom pendant
    "hyrule-historian": symbols.compass,  // historical records
    "yaze-editor": symbols.sword,        // editing power
    "mesen2-oos": symbols.crystal,       // debug crystal
    "afs": symbols.triforceSmall,        // general
  };
  return serverSymbolMap[name] ?? symbols.triforceSmall;
}

// ---------------------------------------------------------------------------
// Mode theming — routing mode gets a goddess-aligned color
// ---------------------------------------------------------------------------

export function modeColor(mode: string, c: any = colors): string {
  const normalizedMode = normalizeModelName(mode);
  if (ORACLE_MODE_LEGACY_ALIASES.has(normalizedMode)) {
    return c.nayru;
  }
  switch (normalizedMode) {
    case "oracle":       return c.nayru;     // wisdom routes
    case "broadcast":    return c.farore;    // courage to many
    case "orchestrator": return c.triforce;  // cloud planner drives
    case "manual":       return c.dim;       // direct control
    default:             return c.triforce;
  }
}

/** Map interaction UI mode to thematic colors. */
export function uiModeColor(mode: string, c: any = colors): string {
  switch (mode) {
    case "admin":  return c.din;
    case "build":  return c.farore;
    case "plan":   return c.nayru;
    case "review": return c.triforce;
    default:       return c.dim;
  }
}

// ---------------------------------------------------------------------------
// Heart container — context window as Zelda health
// ---------------------------------------------------------------------------

export function heartBar(
  percent: number,
  maxHearts: number = 10,
  c: any = colors,
): { display: string; color: string } {
  // Hearts represent remaining capacity (100% used = 0 hearts)
  const remaining = Math.round(((100 - percent) / 100) * maxHearts);
  const full = Math.max(0, Math.min(maxHearts, remaining));
  const empty = maxHearts - full;
  const display = symbols.heart.repeat(full) + symbols.heartEmpty.repeat(empty);

  const color =
    full <= 2 ? c.error : full <= 4 ? c.heartLow : c.heartFull;

  return { display, color };
}

// ---------------------------------------------------------------------------
// Rupee — token counter formatting
// ---------------------------------------------------------------------------

export function formatTokens(count: number, c: any = colors): { text: string; color: string } {
  if (count === 0) return { text: "", color: c.dim };
  const num = count > 1000 ? `${(count / 1000).toFixed(1)}k` : `${count}`;
  const color =
    count > 10000
      ? c.rupeeRed
      : count > 3000
        ? c.rupeeBlue
        : c.rupeeGreen;
  return { text: `${symbols.rupee} ${num}`, color };
}
