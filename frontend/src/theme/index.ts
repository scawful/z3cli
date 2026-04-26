/** Zelda-themed terminal color palette, symbols, and styling. */

import {
  isActionLikeModel,
  isCloudLikeModel,
  isPlanLikeModel,
  isToolLikeModel,
  normalizeModelName,
} from "../utils/models.js";

// ---------------------------------------------------------------------------
// Palettes — each theme is a *place* in the Oracle universe with its own
// chrome (primary/accent/text/borders). Goddess colors stay semantic and
// don't vary per theme — they identify models, servers, and modes.
// ---------------------------------------------------------------------------

interface Palette {
  primary: string;       // brand accent / triforce
  accent: string;        // secondary accent
  text: string;          // main text color
  dim: string;           // separators, soft secondary text
  muted: string;         // labels, third-tier text
  borderRest: string;    // default chrome border
  borderActive: string;  // hovered/focused border
  heartFull: string;     // context-window hearts when healthy
}

const themes: Record<string, Palette> = {
  // Default — warm gold parchment, the home castle palette.
  hyrule: {
    primary:      "#FFD700",
    accent:       "#F59E0B",
    text:         "#E5E7EB",
    dim:          "#6B7280",
    muted:        "#9CA3AF",
    borderRest:   "#FFD700",
    borderActive: "#FBBF24",
    heartFull:    "#EF4444",
  },
  // Volcanic underground — ember reds and lava oranges. Dim/muted are
  // warm-tinted neutrals (not raw red-700/red-900) so secondary text and
  // separators stay legible on dark terminals.
  subrosia: {
    primary:      "#EF4444",
    accent:       "#F97316",
    text:         "#FED7AA",
    dim:          "#8C6F6F",
    muted:        "#C5A5A5",
    borderRest:   "#DC2626",
    borderActive: "#FCA5A5",
    heartFull:    "#FBBF24",
  },
  // Time-traveler's land — calm teal / nayru blue.
  labrynna: {
    primary:      "#3B82F6",
    accent:       "#14B8A6",
    text:         "#DBEAFE",
    dim:          "#475569",
    muted:        "#64748B",
    borderRest:   "#2563EB",
    borderActive: "#93C5FD",
    heartFull:    "#FBBF24",
  },
  // Twilight realm — veran purple, shadow orange. Dim/muted are cool
  // purple-tinted neutrals (not raw violet-900/violet-600) so secondary text
  // and separators stay legible on dark terminals.
  twilight: {
    primary:      "#8B5CF6",
    accent:       "#F97316",
    text:         "#E9D5FF",
    dim:          "#6B6584",
    muted:        "#9C90B5",
    borderRest:   "#7C3AED",
    borderActive: "#C4B5FD",
    heartFull:    "#F97316",
  },
};

// Legacy theme names map to their nearest new equivalent. Keeps saved
// `~/.config/z3cli/ui-settings.json` files working through one release.
const themeAliases: Record<string, keyof typeof themes> = {
  gold:  "hyrule",
  red:   "subrosia",
  blue:  "labrynna",
  green: "labrynna",
};

export const THEME_NAMES = ["hyrule", "subrosia", "labrynna", "twilight"] as const;
export type ThemeName = (typeof THEME_NAMES)[number];

export function resolveThemeName(name: string): ThemeName {
  if ((THEME_NAMES as readonly string[]).includes(name)) return name as ThemeName;
  return (themeAliases[name] as ThemeName | undefined) ?? "hyrule";
}

export function getThemeColors(theme: string = "hyrule") {
  const p = themes[resolveThemeName(theme)]!;
  return {
    // The three goddesses (semantic — never vary per theme)
    din: "#EF4444",        // red — power, optimization
    nayru: "#3B82F6",      // blue — wisdom, explanation
    farore: "#22C55E",     // green — courage (semantic; broadcast/build mode + hyrule-historian server)

    // Helpers + Oracle pantheon (semantic — never vary per theme)
    navi: "#4FCFFF",       // cyan — fairy glow, FIM/autocomplete/quick-debug helper
    veran: "#8B5CF6",      // purple — sorceress of shadows
    majora: "#F97316",     // orange — mask of chaos
    hylia: "#EC4899",      // pink — golden goddess
    oracleTools: "#FBBF24", // amber — tool-calling

    // Theme chrome (varies per theme)
    triforce:     p.primary,
    accent:       p.accent,
    border:       p.borderRest,
    borderActive: p.borderActive,
    text:         p.text,
    dim:          p.dim,
    muted:        p.muted,

    // Status (semantic)
    success: "#22C55E",
    error:   "#EF4444",
    warning: "#F59E0B",

    // Roles (semantic)
    user:      "#5EEAD4",
    assistant: "#A78BFA",
    system:    "#6B7280",
    tool:      "#FBBF24",

    // Hearts (context)
    heartFull:  p.heartFull,
    heartLow:   "#F59E0B",
    heartEmpty: "#4B5563",

    // Rupees (token counter — semantic by amount)
    rupeeGreen: "#22C55E",
    rupeeBlue:  "#3B82F6",
    rupeeRed:   "#EF4444",

    // Hex addresses
    address: p.primary,
  };
}

// Default export for backward compatibility
export const colors = getThemeColors("hyrule");

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
  "nayru-q8": colors.nayru,
  navi: colors.navi,
  "navi-q4km": colors.navi,
  "navi-q8": colors.navi,
  farore: colors.navi,        // back-compat alias of navi
  "farore-q4km": colors.navi, // back-compat alias of navi-q4km
  "farore-q8": colors.navi,   // back-compat alias of navi
  veran: colors.veran,
  majora: colors.majora,
  hylia: colors.hylia,
  oracle: colors.nayru,
  "oracle-fast": colors.oracleTools,
  "oracle-qwen35-9b": colors.nayru,
};

const exactModelSymbolMap: Record<string, string> = {
  din: symbols.triforce,
  nayru: symbols.crystal,
  "nayru-q8": symbols.crystal,
  navi: symbols.pendant,
  "navi-q4km": symbols.pendant,
  "navi-q8": symbols.pendant,
  farore: symbols.pendant,
  "farore-q4km": symbols.pendant,
  "farore-q8": symbols.pendant,
  veran: symbols.crystal,
  majora: symbols.shield,
  hylia: symbols.pendant,
  oracle: symbols.compass,
  "oracle-fast": symbols.sword,
  "oracle-qwen35-9b": symbols.compass,
};
const ORACLE_MODE_LEGACY_ALIASES = new Set(["oracle-main", "switchhook"]);

export function modelColor(name: string, c: any = colors): string {
  const exactModelColorMap: Record<string, string> = {
    din: c.din,
    nayru: c.nayru,
    "nayru-q8": c.nayru,
    navi: c.navi,
    "navi-q4km": c.navi,
    "navi-q8": c.navi,
    farore: c.navi,
    "farore-q4km": c.navi,
    "farore-q8": c.navi,
    veran: c.veran,
    majora: c.majora,
    hylia: c.hylia,
    oracle: c.nayru,
    "oracle-fast": c.oracleTools,
    "oracle-qwen35-9b": c.nayru,
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
    "nayru-q8": symbols.crystal,
    navi: symbols.pendant,
    "navi-q4km": symbols.pendant,
    "navi-q8": symbols.pendant,
    farore: symbols.pendant,
    "farore-q4km": symbols.pendant,
    "farore-q8": symbols.pendant,
    veran: symbols.crystal,
    majora: symbols.shield,
    hylia: symbols.pendant,
    oracle: symbols.compass,
    "oracle-fast": symbols.sword,
    "oracle-qwen35-9b": symbols.compass,
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
