# Zelda-first workflows

Quick prompts and host actions are defined in code so they stay versioned with the app:

- **Presets** — [`ios/ZeldaRemoteCore/Sources/ZeldaRemoteCore/ZeldaWorkflows.swift`](../../ios/ZeldaRemoteCore/Sources/ZeldaRemoteCore/ZeldaWorkflows.swift) (`ZeldaWorkflows.presets`): ASM hooks, crash tracing, dungeon room validation, session resume hints.
- **Slash commands** — `ZeldaWorkflows.slashHints`: only commands that exist in [`z3cli/app/serve.py`](../../z3cli/app/serve.py) (`handle_command`), e.g. `/sessions`, `/status`.
- **Models list** — JSON-RPC method `models` (Ink uses `Backend.request("models")`; not `/models` slash).

## Session resume entry points

From mobile, users typically:

1. Open **Connect**, authenticate to the bridge, wait for `ready`.
2. Run **`/sessions`** via Host actions (result echoed as a system line in chat — consider pretty-printing JSON in a later iteration).
3. Run **`/resume`** with the chosen id when you add a dedicated resume UI, or paste the slash in chat as a future enhancement.

The Python side persists sessions under the host user’s data dir (`z3cli/core/session.py`); the phone never reads those files directly.

## Suggested follow-ups

- Dedicated **Sessions** list UI parsing `/sessions` JSON.
- **Pinned ROM / workspace** display from `ready.workspace` and `rom_path`.
- **Model picker** bound to `/model` or registry-aware flows once you mirror `commands/index.ts` selectively.
