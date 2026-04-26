# Handoff — Ink UI Tier 1 Identity Uplift (2026-04-25)

Tier 1 of the Ink UI visual uplift planned in
`/Users/scawful/.claude/plans/review-the-ui-ux-of-cuddly-neumann.md`.
Goal: amplify the existing Oracle/Hyrule identity so the frontend reads as a
bespoke console rather than a tinted utility CLI.

## What Shipped

### Whole-palette themes
`frontend/src/theme/index.ts`

- Promoted `palettes` from `{primary, accent}` to a full `Palette` shape:
  `{primary, accent, text, dim, muted, borderRest, borderActive, heartFull}`.
- Replaced the four single-color tints (gold/green/red/blue) with four
  cohesive **location** themes:
  - `hyrule` (default) — warm gold + parchment text
  - `subrosia` — ember red + lava orange
  - `labrynna` — deep blue + cool whites
  - `twilight` — veran purple + shadow orange
- Goddess colors (`din/nayru/farore/veran/majora/hylia/oracleTools`) and
  rupee colors stay **outside** the palette — they're semantic
  (model/server/mode identity) and must not vary with theme.
- New exports: `THEME_NAMES`, `ThemeName`, `resolveThemeName(name)`.

### Settings / commands compatibility
`frontend/src/hooks/useSettings.ts` · `frontend/src/commands/index.ts`

- `UITheme` now derives from `THEME_NAMES`.
- `coerceTheme` upgrades persisted legacy values:
  `gold → hyrule`, `red → subrosia`, `blue → labrynna`, `green → labrynna`.
- `/settings theme gold` (etc.) still works — the slash-command parser maps
  legacy aliases to their new equivalents.
- Saved `~/.config/z3cli/ui-settings.json` files keep working without user
  action.

### Welcome banner
`frontend/src/components/WelcomeBanner.tsx`

- Replaced the 2-line triforce with a 5-line handlaid sigil.
- Added `PressStartPulse` — animates `▸ PRESS START ◂` for 3 s via
  `useAnimatedFrame`, then settles to a static dimmed line.
- FILE 1 panel labels rendered in NES-spaced caps (`Q U E S T`, `M A P`,
  `G E A R`, `I T E M S`, `L O A D`).
- No new dependencies; rejected `ink-big-text` and `ink-gradient` to keep the
  pixel-art identity.

### Persistent keyboard hint footer
`frontend/src/components/KeyHintBar.tsx` (new) · `frontend/src/components/App.tsx`

- New render-only component below `StatusBar` showing
  `[Ctrl+P] Palette · [Tab] Complete · [Shift+Tab] Mode`.
- Hides when any modal is open (Settings, Help, Model Manager, Permission,
  Tool Review) or terminal width < 80.
- `KEYBOARD_LEGEND_ITEMS` lives in `KeyHintBar.tsx`; `App.tsx` re-exports
  it for back-compat with `App.test.ts`.
- `App.tsx` shed the inline `KeyboardLegend` helper.

### Border vocabulary
Codified roles:

| Style    | Role                                  |
|----------|---------------------------------------|
| `round`  | persistent chrome (TitleBar)          |
| `single` | transcript messages (left-only)       |
| `double` | modals/dialogs/panels                 |
| `bold`   | transient or destructive (errors)     |

Concrete moves:
- `BackendErrorBanner.tsx` — `double → bold`.
- `SubagentPanel.tsx` — inner row borders `double → single`; outer panel
  unchanged.
- Other modal components were already aligned.

## How It Was Validated

- `cd frontend && npm run build` (`tsc`) — clean.
- `cd frontend && npm test` — **198/198 passing**.
- New tests:
  - `frontend/src/theme/index.test.ts` — palette shape invariance, alias
    resolution, semantic invariance for goddess and rupee colors, distinct
    primary per theme, and selected `modelColor`/`serverColor`/`modeColor`
    behavior.
  - `frontend/src/components/KeyHintBar.test.ts` — legend list shape,
    App.tsx re-export equivalence.
- Updated tests:
  - `frontend/src/hooks/useSettings.test.ts` — repaired-default expectation
    is now `hyrule`.
  - `frontend/src/commands/index.test.ts` — `/settings theme` usage message
    regex matches the new theme names.

**Manual TUI verification still required** — automated tests don't cover
visual feel. Spin up `cd frontend && npm run dev` and:

1. Welcome banner shows the sigil + PRESS START pulse for ~3 s, then static.
2. Settings panel (Esc → Gear tab → "UI Theme" → Space) cycles all four
   themes; chrome (border, hearts, accents) shifts cohesively while
   goddess-colored model badges stay constant.
3. Resize narrower than 80 cols — KeyHintBar disappears, banner persists.
4. Trigger a backend error — banner uses bold border.
5. Run a multi-subagent task — outer panel `double`, inner rows `single`
   (less visual noise).

## Cleanup Landed After Initial Handoff

A code-review pass after the initial Tier 1 ship surfaced two issues fixed
in the same branch:

1. **KeyHintBar visibility / row reservation drifted.** App.tsx reserved a
   transcript row whenever `shouldShowKeyboardLegend(rows)` was true, but
   the bar itself also hid on modal open and `width < 80`. So opening
   Settings or shrinking the terminal left a phantom blank row at the
   bottom. Fixed by introducing `shouldShowKeyHintBar({rows, width,
   modalOpen})` in `utils/transcript.ts` and feeding the same boolean to
   both the `<KeyHintBar visible=...>` prop and
   `computeTranscriptViewportHeight(...)`. KeyHintBar's API simplified to
   a single `visible` prop. Test added in `transcript.test.ts`.

2. **Contrast pass on subrosia + twilight `dim`/`muted`.** Originals were
   raw red-900/red-700 and violet-900/violet-600 — near-invisible on dark
   terminals. Replaced with warm- and cool-tinted mid-lightness neutrals
   (`#8C6F6F`/`#C5A5A5` for subrosia, `#6B6584`/`#9C90B5` for twilight)
   that retain the location feel. Locked the floor with a WCAG-style
   relative-luminance invariant in `theme/index.test.ts` requiring
   `dim ≥ 0.08` and `muted ≥ 0.15` for every theme.

## Open Risks

- **Color depth.** Primaries still clamp to 256-color under
  `TERM=xterm-256color`. The contrast pass applies to truecolor; under
  256-color the dim/muted may quantize differently. Not yet verified.
- **Legacy alias removal.** Aliases for `gold/red/blue/green` live in three
  places: `themeAliases` in `theme/index.ts`, `coerceTheme` in
  `hooks/useSettings.ts`, and the `legacyMap` in `commands/index.ts`'s
  `parseEnumSetting`. Remove together when the deprecation window closes.
- **`PressStartPulse` cadence.** Shared `useAnimatedFrame` clock keeps
  ticking at 600 ms while `WelcomeBanner` is mounted (until first prompt
  unmounts it). Negligible in practice.
- **labrynna borderline.** `labrynna.dim` (#475569) sits at luminance
  ~0.088 — just above the 0.08 floor. If the floor moves, labrynna will
  need its own bump.

## What's Next (Tier 2 / Tier 3 — Deferred)

Not blocked by Tier 1. Pull from
`/Users/scawful/.claude/plans/review-the-ui-ux-of-cuddly-neumann.md` when
prioritizing the next slice. Capsule list:

### Tier 2 — readability & motion polish
- Multi-row `StatusBar` for narrow terminals (< 100 cols), with mode-tinted
  left gutter cell.
- Braille spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) for streaming text; keep crystal spinner
  on tool calls and subagents.
- Message bubble visual rhythm: collapse role headers on consecutive
  same-role messages; left-corner glyphs for first/middle/last in a group.
- Tool call header thematic flourish (`❯ tool · server · summary · 1.2s`).
- Subagent tree gutters using `│ `/`└─` instead of numeric indentation; cap
  visible spinners for performance.

### Tier 3 — optional extras
- Toast stack (`ToastStack` + `useToast`) for transient command feedback
  (`Theme set to subrosia`, `Tools paused`) with goddess-color tinting by
  category.
- Title bar identity flourish — `▲ ▲ ▲ z3cli` echoing dim triforces.
- Context warning at 90 % — append `{compass} consider /compact` to title
  bar.

## Files Touched

```
frontend/src/theme/index.ts                        modified  (+ contrast pass)
frontend/src/theme/index.test.ts                   added     (+ luminance invariant)
frontend/src/hooks/useSettings.ts                  modified
frontend/src/hooks/useSettings.test.ts             modified
frontend/src/commands/index.ts                     modified
frontend/src/commands/index.test.ts                modified
frontend/src/components/WelcomeBanner.tsx          rewritten
frontend/src/components/KeyHintBar.tsx             added     (slimmed in cleanup)
frontend/src/components/KeyHintBar.test.ts         added
frontend/src/components/App.tsx                    modified  (+ shared visibility)
frontend/src/components/BackendErrorBanner.tsx     modified
frontend/src/components/SubagentPanel.tsx          modified
frontend/src/utils/transcript.ts                   modified  (+ shouldShowKeyHintBar)
frontend/src/utils/transcript.test.ts              modified  (+ visibility test)
```
