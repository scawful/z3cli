# vscode-z3cli

VSCode/Cursor/Antigravity extension for the [z3cli](../../README.md) local-AI
runtime. Brings z3ui-style chat, slash commands, and FIM autocomplete into the
editor, talking to LM Studio / llama.cpp models through the same `--serve`
JSON-RPC channel that powers `z3ui`.

## Features

- **Sidebar chat** — webview that streams text/thinking/tool/subagent events
  from `z3cli --serve`. Same model picker, mode picker, and route picker as
  `z3ui`. `@file` and `#room:0x45` references work.
- **Inline FIM autocomplete** — `vscode.languages.registerInlineCompletionItemProvider`
  hits `/v1/completions` directly with Qwen FIM tokens. Hot path is local-only;
  cold path falls back to a `complete` RPC on `z3cli --serve` so the model can
  be auto-loaded.
- **Slash command palette** — the 50+ z3cli slash commands surface as
  `Z3CLI: …` entries in the command palette plus a TreeView in the activity
  bar. The same registry your terminal `z3cli` uses.
- **Activity bar** — three views: Chat (webview), Routes (active backend +
  model summary), Commands (grouped command palette).

## Build

```bash
npm install
npm run build               # esbuild → out/extension.js
npm run package             # @vscode/vsce package
./scripts/install-vsix.sh   # install into stock VSCode + Cursor + Antigravity
```

## Settings (`z3cli.*`)

| Key | Default | Notes |
|---|---|---|
| `pythonPath` | `python3` | Used for `python -m z3cli --serve` |
| `module` | `z3cli` | Module passed to `python -m`; use `app` only with `PYTHONPATH` pointed at repo `src` |
| `checkoutPath` | `""` | Local z3cli checkout path; empty auto-detects common locations |
| `serveCommand` | `[]` | Full command override, e.g. `["z3cli"]` |
| `extraArgs` | `[]` | Appended after `--serve` |
| `maxRestarts` | `8` | Backend restart limit after crashes; `0` means unlimited |
| `workspace` | `""` | Workspace directory passed to z3cli; empty uses the first editor workspace folder |
| `rom` | `""` | ROM path passed to z3cli on launch |
| `studioApiBase` | `http://127.0.0.1:1234/v1` | LM Studio |
| `llamacppApiBase` | `http://127.0.0.1:8080/v1` | llama.cpp |
| `fim.enabled` | `true` | Inline completions toggle |
| `fim.endpoint` | `auto` | `auto`, `studio`, or `llamacpp` |
| `fim.model` | `navi` | Model alias for completion requests |
| `fim.maxTokens` | `96` | |
| `fim.temperature` | `0.1` | |
| `fim.stopTokens` | Qwen FIM stops | Stop tokens passed to completion endpoints |
| `fim.debounceMs` | `150` | |
| `fim.languages` | asar/c/cpp/ts/js/py/md | |
| `fim.contextPrefixChars` | `2000` | Prefix budget included in FIM prompts |
| `fim.contextSuffixChars` | `1000` | Suffix budget included in FIM prompts |
| `chat.defaultMode` | `""` | Optional startup routing mode |
| `chat.defaultRoute` | `""` | Applied at startup (e.g. `oracle-pro-5090`) |

## Architecture

```
+-------------------+    spawn    +-----------------------+
| extension.ts      |───────────▶| python -m z3cli       |
|  - chat panel     | NDJSON RPC  |   --serve             |
|  - command palette|◀──────────| (chat / command /      |
|  - InlineCompProv |             |  complete handlers)    |
+---------┬---------+             +-----------+-----------+
          │                                   │
          │ POST /v1/completions              │ resolve_request_model
          ▼                                   ▼
+-------------------+             +-----------------------+
| LM Studio /        |             | LM Studio / llama.cpp |
| llama.cpp (local)  |             | inference + auto-load |
+-------------------+             +-----------------------+
```

The hot FIM path bypasses Python for latency; the cold path goes through
`z3cli` so model auto-load works.

## Protocol

Generated from `src/app/ipc_schema.py` via:

```bash
python3 scripts/generate_protocol_ts.py
```

That writes both `frontend/src/ipc/protocol.generated.ts` and
`extensions/vscode-z3cli/src/ipc/protocol.generated.ts`, and copies
`command_catalog.json` into the extension. Run it whenever the IPC schema
changes.
