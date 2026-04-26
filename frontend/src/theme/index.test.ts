import test from "node:test";
import assert from "node:assert/strict";

import {
  THEME_NAMES,
  getThemeColors,
  resolveThemeName,
  modelColor,
  modelSymbol,
  serverColor,
  modeColor,
  uiModeColor,
} from "./index.js";

test("THEME_NAMES are the four location themes", () => {
  assert.deepEqual(THEME_NAMES, ["hyrule", "subrosia", "labrynna", "twilight"]);
});

test("resolveThemeName accepts new names verbatim", () => {
  for (const name of THEME_NAMES) {
    assert.equal(resolveThemeName(name), name);
  }
});

test("resolveThemeName upgrades legacy theme aliases", () => {
  assert.equal(resolveThemeName("gold"), "hyrule");
  assert.equal(resolveThemeName("red"), "subrosia");
  assert.equal(resolveThemeName("blue"), "labrynna");
  assert.equal(resolveThemeName("green"), "labrynna");
});

test("resolveThemeName falls back to hyrule for unknown values", () => {
  assert.equal(resolveThemeName("kakariko"), "hyrule");
  assert.equal(resolveThemeName(""), "hyrule");
});

test("getThemeColors returns the same key shape for every theme", () => {
  const reference = Object.keys(getThemeColors("hyrule")).sort();
  for (const name of THEME_NAMES) {
    const keys = Object.keys(getThemeColors(name)).sort();
    assert.deepEqual(keys, reference, `theme ${name} key shape diverges`);
  }
});

test("goddess colors are identical across themes (semantic invariance)", () => {
  const goddessKeys = ["din", "nayru", "farore", "navi", "veran", "majora", "hylia", "oracleTools"] as const;
  const reference = getThemeColors("hyrule");
  for (const name of THEME_NAMES) {
    const palette = getThemeColors(name);
    for (const key of goddessKeys) {
      assert.equal(
        palette[key],
        reference[key],
        `goddess color ${key} should not vary between themes (hyrule vs ${name})`,
      );
    }
  }
});

test("specialist quant aliases inherit their canonical color and symbol", () => {
  const palette = getThemeColors("hyrule");
  const pairs: Array<[string, string]> = [
    ["navi-q4km", "navi"],
    ["navi-q8", "navi"],
    ["farore", "navi"],         // back-compat alias points to the navi identity
    ["farore-q4km", "navi"],
    ["farore-q8", "navi"],
    ["nayru-q8", "nayru"],
    ["oracle-qwen35-9b", "oracle"],
  ];
  for (const [alias, canonical] of pairs) {
    assert.equal(
      modelColor(alias, palette),
      modelColor(canonical, palette),
      `color: ${alias} should match ${canonical}`,
    );
    assert.equal(
      modelSymbol(alias),
      modelSymbol(canonical),
      `symbol: ${alias} should match ${canonical}`,
    );
  }
});

test("navi identity color is distinct from the farore goddess color", () => {
  // The semantic c.farore (green) is still used by modeColor(broadcast),
  // uiModeColor(build), and serverColor(hyrule-historian). Renaming the
  // model to navi must NOT collapse the two.
  const palette = getThemeColors("hyrule");
  assert.notEqual(palette.navi, palette.farore);
  assert.equal(modelColor("navi", palette), palette.navi);
  assert.equal(modeColor("broadcast", palette), palette.farore);
});

test("rupee colors stay semantic across themes", () => {
  const rupeeKeys = ["rupeeGreen", "rupeeBlue", "rupeeRed"] as const;
  const reference = getThemeColors("hyrule");
  for (const name of THEME_NAMES) {
    const palette = getThemeColors(name);
    for (const key of rupeeKeys) {
      assert.equal(palette[key], reference[key]);
    }
  }
});

test("each theme picks a distinct primary color", () => {
  const primaries = THEME_NAMES.map((name) => getThemeColors(name).triforce);
  assert.equal(new Set(primaries).size, primaries.length);
});

test("modelColor uses the active palette's chrome for cloud-like fallbacks", () => {
  const hyrule = getThemeColors("hyrule");
  const twilight = getThemeColors("twilight");
  // CLOUD_NAME_HINTS includes "claude" — treated as cloud-like and tinted
  // by the active theme's primary, so it shifts when the theme shifts.
  assert.equal(modelColor("claude-sonnet", hyrule), hyrule.triforce);
  assert.equal(modelColor("claude-sonnet", twilight), twilight.triforce);
});

test("modelColor keeps goddess models on their semantic colors regardless of theme", () => {
  const hyrule = getThemeColors("hyrule");
  const subrosia = getThemeColors("subrosia");
  assert.equal(modelColor("din", hyrule), modelColor("din", subrosia));
  assert.equal(modelColor("nayru", hyrule), modelColor("nayru", subrosia));
  assert.equal(modelColor("farore", hyrule), modelColor("farore", subrosia));
});

test("serverColor maps known servers to goddess colors", () => {
  const palette = getThemeColors("hyrule");
  assert.equal(serverColor("book-of-mudora", palette), palette.nayru);
  assert.equal(serverColor("hyrule-historian", palette), palette.farore);
  assert.equal(serverColor("yaze-editor", palette), palette.din);
});

// WCAG-style relative luminance — sRGB hex → 0..1, used to floor the
// readability of `dim` and `muted` against a dark terminal background.
function relativeLuminance(hex: string): number {
  const m = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(hex);
  if (!m) throw new Error(`expected #rrggbb, got ${hex}`);
  const channel = (raw: number): number => {
    const v = raw / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const r = channel(parseInt(m[1]!, 16));
  const g = channel(parseInt(m[2]!, 16));
  const b = channel(parseInt(m[3]!, 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

test("dim/muted maintain a readability floor across every theme", () => {
  // Floors picked to catch the original subrosia/twilight regressions
  // (dim ~0.05, muted ~0.12) while leaving palette identity intact.
  const DIM_FLOOR = 0.08;
  const MUTED_FLOOR = 0.15;
  for (const name of THEME_NAMES) {
    const palette = getThemeColors(name);
    const dim = relativeLuminance(palette.dim);
    const muted = relativeLuminance(palette.muted);
    assert.ok(
      dim >= DIM_FLOOR,
      `${name}.dim luminance ${dim.toFixed(3)} < floor ${DIM_FLOOR}`,
    );
    assert.ok(
      muted >= MUTED_FLOOR,
      `${name}.muted luminance ${muted.toFixed(3)} < floor ${MUTED_FLOOR}`,
    );
    assert.ok(
      muted >= dim,
      `${name}.muted (${muted.toFixed(3)}) should be >= dim (${dim.toFixed(3)})`,
    );
  }
});

test("modeColor and uiModeColor return strings for all known inputs", () => {
  const palette = getThemeColors("hyrule");
  for (const mode of ["oracle", "broadcast", "orchestrator", "manual", "unknown"]) {
    assert.equal(typeof modeColor(mode, palette), "string");
  }
  for (const mode of ["chat", "plan", "review", "build", "admin"]) {
    assert.equal(typeof uiModeColor(mode, palette), "string");
  }
});
