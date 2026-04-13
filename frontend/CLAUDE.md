# CLAUDE.md — z3cli Frontend

## Structure
- `commands/` — command dispatch table (add entries, not branches)
- `components/` — render only, no business logic
- `hooks/` — state/effects only, no JSX
- `contexts/` — shared state (currently: SettingsContext)
- `theme/` — pure functions, no React
- `utils/` — stateless helpers (path.ts)

## Rules

**Shell execution (`!`):** Handled in `App.tsx` `handleSubmit`. Logic lives in
`executeShell()` exported from `commands/index.ts`. Runs in `config.workspace`.

**UI mode (Shift+Tab):** Cycles `chat → plan → review → build → admin`. Owned by
`useSettings` (`cycleMode`). Displayed in `StatusBar`. Admin mode auto-approves
tool permissions. Read via `useSettingsContext().settings.uiMode`.

**Tool permissions:** Backend sends `tool/permission_request` notification before
executing each tool. Frontend shows `PermissionDialog` unless `uiMode === "admin"`.
`approveTool` / `denyTool` send `tool/approve` / `tool/deny` commands to backend.
Engine holds an `asyncio.Event` until the response arrives.

**Commands:** Add to the table in `commands/index.ts`. Each handler is a
named async function. Use the file-local `runCmd` wrapper for anything
calling `sendCommand`. Never add command handling to `App.tsx`.

**Animation:** Use `useAnimatedFrame(frames, ms)` — do not re-implement
`useState + setInterval`. There is one implementation.

**Settings:** Read via `useSettingsContext()` inside any component.
App.tsx owns the state and provides it via `SettingsContext.Provider`.
Never prop-drill `settings` through component trees.

**Path display:** Use `shortenPath(p)` and `basename(p)` from `utils/path.ts`.
Do not repeat `.replace(/^\/Users\/[^\/]+/, "~")`.

**Errors:** Commands surface errors via `addSystemMessage("Error: ...")`.
The `error` state is for backend-level failures only (connection, crash).

**Naming:** Functions are verb+object. No `result`, `r`, `data`, `items`.
No JSX comments that restate the component name.

**Dead exports:** If you add an export, grep for it. If no importers, delete it.

## Files never to bloat
- `App.tsx` — currently ~200 lines, owns lifecycle wiring only
- `theme/index.ts` — pure constants and formatters, nothing stateful
- `commands/index.ts` — one entry per command, `runCmd` stays unexported

## Derived from
Style extrapolated from yaze (C++ ROM editor) and premia (C++ trading app),
both handwritten by the project owner. See STYLE.md for the full guide.
