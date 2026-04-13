# z3cli Frontend Style Guide

Grounded in patterns observed across yaze and premia — the two codebases
written by hand and allowed to mature over time. The principles here are
extracted from what was actually done, not from what is generally advised.

---

## Directory contract

Each directory has exactly one concern. Adding a file to the wrong place
is a design error, not a formatting error.

```
src/
  commands/     Command dispatch table — handlers are data, not code
  components/   React components — rendering only, no computation
  contexts/     Shared state that crosses component trees
  hooks/        State and effects — no JSX, no rendering
  ipc/          Protocol types and backend communication
  theme/        Colors, symbols, formatters — pure functions
  utils/        Small, stateless helpers (path, format)
```

Rules:
- `hooks/` never imports from `components/`
- `commands/` never imports from `components/`
- `theme/` has no side effects and no React imports
- `utils/` has no React imports

---

## Component contract

A component receives props, renders JSX. It does not compute business logic,
format data, or manage complex state. If a component is doing non-trivial
work before the return statement, that work belongs in a hook or utility.

**Right:**
```tsx
export function StatusBar({ model, workspace }: StatusBarProps) {
  const { settings } = useSettingsContext();   // read shared state
  const tok = formatTokens(promptTokens + completionTokens);  // pure fn
  return <Box>...</Box>;
}
```

**Wrong:**
```tsx
export function StatusBar({ model, workspace }: StatusBarProps) {
  const [frame, setFrame] = useState(0);        // should be useAnimatedFrame
  useEffect(() => { setInterval(...) }, []);    // repeated boilerplate
  const shortPath = workspace                   // should be utils/path.ts
    .replace(/^\/Users\/[^/]+/, "~")
    .replace(/\/src\/hobby\//, "/");
  ...
}
```

File-local helpers (functions not exported) go at the bottom of the file,
after the component. They are never exported — if another file needs them,
they move to `utils/`.

---

## Hook contract

Hooks encapsulate state and effects. They return typed objects, never JSX.
The name encodes what the hook does (`useBackend`, `useSettings`,
`useAnimatedFrame`), not where it's used.

`useAnimatedFrame` replaces every `useState(0)` + `useEffect setInterval`
spinner. There is exactly one implementation.

---

## Commands are data

The command dispatch table in `src/commands/index.ts` maps command strings
to handler functions. Adding a command means adding one entry to the table.
It does not mean adding a branch to a 300-line if/else chain.

The table pattern comes directly from how premia's service layer maps HTTP
routes to methods: routes are data, handlers are functions, the dispatcher
is a loop.

```typescript
const COMMANDS: Record<string, Handler> = {
  "/help": async (_, ctx) => ctx.addSystemMessage(HELP_TEXT),
  "/model": (args, ctx) => runCmd("/model", args, ctx, (r) => { ... }),
  // one entry per command, no repetition
};
```

The `runCmd` helper wraps `sendCommand(...).then(...).catch(...)` once.
It is not exported — it is the anonymous namespace equivalent in TypeScript.

---

## Context over prop drilling

If a value needs to cross more than two component boundaries, it belongs
in a context. The threshold is not about architecture — it is about
maintenance cost when the value changes.

`UISettings` was drilled through four components before being moved to
`SettingsContext`. Each of those four components had to update their prop
interfaces when a new setting was added. With context, only `useSettings`
and `SettingsContext` change.

The pattern in this codebase:
- App.tsx owns the state (`useSettings`)
- App.tsx provides it (`SettingsContext.Provider`)
- Consumers call `useSettingsContext()` — one import, no props

---

## Naming

Names encode intent. The name `handleSubmit` tells you a form was submitted.
The name `dispatchCommand` tells you what is dispatched and where it goes.

Guidelines:
- Functions: verb + object (`dispatchCommand`, `shortenPath`, `formatTokens`)
- Components: noun that describes what is rendered (`TitleBar`, `SettingsPanel`)
- Hooks: `use` + what is managed (`useAnimatedFrame`, `useSettingsContext`)
- Context files: `{Thing}Context.tsx`, one context per file
- Types/interfaces: noun, PascalCase, no `I` prefix (`CommandContext`, `UISettings`)

Avoid: `result`, `r`, `data`, `items`, `handler`, `manager`, `helper`.
When you find yourself writing `const r = result as ...`, name it what it is:
`const modelResult`, `const sessionList`, `const statsData`.

---

## Comments

The pattern from yaze and premia: comments appear at architecture boundaries,
not at code boundaries. A function named `BuildFallbackSummary` needs no
comment. A three-layer port/adapter boundary needs an overview.

**Write a comment when:**
- The file-level architecture is not obvious from the imports alone
  (see the block comment at the top of `commands/index.ts`)
- A decision was deliberately non-obvious and future readers will undo it
- A sequence of steps must happen in a specific order and the reason isn't
  captured in the types

**Do not write a comment when:**
- The JSX component name already says what it renders (`{/* Title bar */}` before `<TitleBar>`)
- The function name already says what it does
- The comment is a restatement: `// Clear the value` above `setValue("")`

Section banners (`// -----`) are for files over ~150 lines with genuinely
distinct sections. A 30-line component does not need four section banners.

---

## Error handling

There is one path for command errors: `addSystemMessage("Error: ...")`.
This is enforced by `runCmd` in `commands/index.ts`, which every command
that calls `sendCommand` uses. The error state (`error` from `useBackend`)
is for backend-level failures (connection lost, crash) shown in the error panel.

Never mix the two. A command that fails should not set error state. A backend
crash should not appear as a system message.

---

## Animation

`useAnimatedFrame(frames, intervalMs)` is the only way to do frame animation.
There is one implementation in `hooks/useAnimatedFrame.ts`. It replaces
every `useState(0)` + `useEffect(() => setInterval(...))` pair.

If a new animated indicator is needed, use this hook. Do not re-implement it.

---

## What to delete

Dead exports are deleted, not commented out. If a function is exported but
has no importers, it is removed. `formatToolArgs` was an example: exported
from the theme, replaced by an inline component in `MessageBubble`, never
cleaned up.

`grep -r "formatToolArgs"` before every export addition. If it returns only
the definition, delete it.

---

## AI slop checklist

Before adding code, check:

- [ ] Is this logic already done somewhere? (`utils/path.ts`, `useAnimatedFrame`, `runCmd`)
- [ ] Am I adding a branch to an if/else that should be a table entry?
- [ ] Am I prop-drilling past two levels? (use context)
- [ ] Am I re-implementing `useState + setInterval`? (use `useAnimatedFrame`)
- [ ] Am I writing a JSX comment that restates the component name?
- [ ] Am I exporting something with no importer?
- [ ] Am I writing `const r = result as ...`? (give it a real name)
- [ ] Am I adding a duplicate `.catch((e: Error) => addSystemMessage(...))`?  (use `runCmd`)
- [ ] Am I adding a `config &&` guard in a handler that can't run without config?
