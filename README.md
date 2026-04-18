# z3cli

`z3cli` is a model-first Zelda hacking CLI for local LM Studio or `llama.cpp`
models plus Zelda tool servers.

It is built to feel closer to a lightweight Claude Code session than a one-shot
prompt helper:

- interactive REPL
- quick model switching
- routing modes for Zelda specialists
- optional MCP tool calling
- resumable JSONL sessions
- structured `@file` attachments with file metadata
- structured `#kind:query` active-project game references
- sticky tool permissions
- post-write diff review plus verification hooks
- persistent shell commands
- LM Studio auto-load for local models
- optional `llama.cpp` fast-path backend for a pinned main model
- JSON-RPC serve mode for the Ink frontend (`z3ui`)

Current implementation status and recent work: [`docs/cli-current-state.md`](docs/cli-current-state.md)

65816 authoring and emulator workflow plan: [`docs/asm-emulator-roadmap.md`](docs/asm-emulator-roadmap.md)

## Defaults

- chat registry: `~/src/lab/afs-scawful/config/chat_registry.toml`
- LM Studio MCP config: `~/.lmstudio/mcp.json`
- studio API base: `http://127.0.0.1:1234/v1`
- llama.cpp API base: `http://127.0.0.1:8080/v1`
- workspace: `~/src/hobby/oracle-of-secrets`
- ROM: `~/src/hobby/roms/oracle.sfc`
- Public model portfolio note: [`docs/MODEL_PORTFOLIO_PUBLIC.md`](docs/MODEL_PORTFOLIO_PUBLIC.md)
- Halext experimental page draft: [`docs/halext-model-lab-draft.md`](docs/halext-model-lab-draft.md)
- Internal RL threshold policy: [`docs/ZELDA_RLHF_THRESHOLD_POLICY.md`](docs/ZELDA_RLHF_THRESHOLD_POLICY.md)

## Start

```bash
python3 -m z3cli
```

or after install:

```bash
z3cli
```

Useful variants:

```bash
python3 -m z3cli --mode oracle
python3 -m z3cli --model oracle
python3 -m z3cli --model nayru
python3 -m z3cli --tools
python3 -m z3cli --backend llamacpp --llamacpp-model oracle-fast
z3ui --no-auto-start-server --no-auto-load --model oracle
```

`z3cli` and `z3ui` prefer `oracle` as the public default. While that alias still
points at the smaller corrective Qwen3 local model, it can stay loaded as the
daily default. The local specialist bench is intentionally more explicit now:

- `oracle` -> `8B corrective Oracle · q4km`
- `qwen3-oracle-8b` or `oracle-q8` -> `8B corrective Oracle · q8_0`
- `oracle-fast` -> `8-9B fast Oracle · live alias`
- `oracle-pro` -> `27B switchhook Oracle · q4km` manual heavy model
- `nayru` or `nayru-q8` -> `9B Qwen3.5 explainer · q8_0`
- `farore` or `farore-q8` -> `9B Qwen3.5 debug/FIM · q8_0`
- `farore-q4km` -> `9B Qwen3.5 debug/FIM · q4km`
- `majora` or `majora-q4km` -> `9B Qwen3.5 architecture · q4km`
- `hylia` or `hylia-q8` -> `9B Qwen3.5 lore/history · q8_0`
- `hylia-q4km` -> `9B Qwen3.5 lore/history · q4km`

Use `/orchestrator <model|auto>` in `z3ui` when you want to pin or clear the
cloud planner.

## One-Shot Usage

```bash
python3 -m z3cli --mode oracle --prompt "Why does $420C not start DMA?"
python3 -m z3cli --mode oracle --prompt "Generate a safe JSL hook for Link_Main"
python3 -m z3cli --mode oracle --prompt "Explain the BG3 tile upload path" --route-only
```

## Routing Modes

- `manual` - always use the active model alias
- `oracle` - canonical model alias for local Zelda work
- `orchestrator` - use the portfolio router to pick a specialist or fall back to a safe specialist model such as `nayru`
- `broadcast` - fan a prompt out to several model aliases and print each answer separately

Default broadcast set:

- `farore`
- `majora`
- `nayru`

Override it like this:

```bash
python3 -m z3cli --mode broadcast --broadcast-models farore,majora,nayru
```

## Interactive Commands

- `/help`
- `/status`
- `/backend [name]`
- `/backends`
- `/backend-status`
- `/models`
- `/loaded`
- `/servers`
- `/model <name>`
- `/specialist <din|farore|nayru|veran|majora|hylia>`
- `/mode <manual|oracle|orchestrator|broadcast>`
- `/modes`
- `/route <prompt>`
- `/broadcast <alias1,alias2,...>`
- `/load [name]`
- `/unload [name|all]`
- `/workspace <path>`
- `/rom <path|none>`
- `/focus <path|clear>`
- `/tools <on|off>`
- `/tools-write <on|off>`
- `/verify-hooks <on|off>`
- `/permissions [clear]`
- `/shell [command]`
- `/shell-log [n]`
- `/shell-reset`
- `/stats`
- `/save`
- `/sessions`
- `/resume <name>`
- `/compact`
- `/export-training [out]`
- `/reset [model|all]`
- `/exit`

## Notes

- `z3cli` keeps separate history per model, so switching from `nayru` to
  `farore` does not pollute specialist context.
- Sessions persist runtime state including backend, mode, workspace, ROM,
  focus file, write access, verification settings, and sticky permission rules.
- `@path` in the prompt resolves workspace files, and the Ink frontend exposes
  a picker plus structured attachments.
  - attachments are sent as `AttachmentMeta` entries (`path`, `lines`, `chars`)
  - old sessions with path-only attachments continue to load by defaulting
    `lines` and `chars` to `0`
- `#room:0x45`, `#sprite:0x07`, `#map:0x1A`, and related `#kind:query`
  tokens resolve against the active project first.
  - user turns persist resolved game references alongside file attachments
  - room / overworld / message refs can add compact ROM-context packs before the
    model sees the prompt
- In `--serve` mode, write-like tools pause for diff review before the model
  continues. Accepted writes can automatically run repo-aware verification.
- The plain REPL now supports `/verify-hooks`, `/permissions`, and the
  persistent shell commands too, but diff review is still auto-accepted there.
- Auto-load is enabled by default. If a model is not loaded in LM Studio,
  `z3cli` will try `lms load <modelKey> --identifier <alias> --yes`.
- `z3ui` now surfaces concurrently loaded models plus LM Studio-reported loaded
  size, and `/unload` can evict one model or all loaded LM Studio models.
- For fragile local LM Studio setups, `--no-auto-start-server --no-auto-load`
  keeps `z3cli` passive so it talks only to the server you started manually in
  the already-open LM Studio app.
- `oracle` is the canonical entry and currently points at the smaller
  `8B corrective Oracle · q4km` model for daily local work.
- `oracle-q8` and the direct `qwen3-oracle-8b` entry expose the same corrective
  Oracle model as `8B corrective Oracle · q8_0`.
- `oracle-fast` remains the lightweight `8-9B fast Oracle · live alias`.
- `oracle-pro` is the manual-only `27B switchhook Oracle · q4km` model and should
  stay an explicit opt-in, not the default local path.
- `farore`, `hylia`, `majora`, and `nayru` now point at the live local Qwen3.5
  9B exports, with q4km sidecars exposed where you have them.
- Legacy `oracle-main*`, `switchhook*`, and `oracle-tools` names still resolve
  quietly for compatibility, but the real working names are the ones above.
- The local rollout manifest now acts mostly as a lightweight inventory note.
  It is intentionally permissive for local experimentation instead of acting as
  a hard promotion gate.
- MCP servers are loaded from `~/.lmstudio/mcp.json` and filtered to the Zelda
  set by default: `afs`, `book-of-mudora`, `hyrule-historian`,
  `yaze-debugger`, and `yaze-editor`.
- When the workspace looks like a z3dk project, `z3cli` also exposes direct
  read-only `z3lsp` tools for diagnostics, hover, definition, symbol, and
  reference lookups.
- The Ink frontend (`z3ui`) enables xterm SGR mouse reporting so the wheel
  scrolls the transcript. This works in most modern terminals out of the box
  (Terminal.app, iTerm2, WezTerm, Kitty, Alacritty). Inside tmux you need
  `set -g mouse on` in `~/.tmux.conf`; inside screen you need `mousetrack on`.
  Over ssh, the remote terminal is what matters — if the local one supports
  SGR mouse, forwarding usually just works.

## Structured `@file` attachments

When a prompt references workspace files with `@path`, z3cli sends each match as
`AttachmentMeta` over the IPC protocol:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "chat",
  "params": {
    "message": "inspect room.asm",
    "attachments": [
      { "path": "src/room.asm", "lines": 12, "chars": 340 }
    ]
  }
}
```

Current behavior:

- The frontend strips `@file` mentions from outbound message text, so the model
  sees file context via attachment metadata instead of rewritten prose.
- Legacy restore accepts path-only saved attachments and fills missing counters
  with `lines: 0`, `chars: 0`.

## Legacy attachment compatibility

Sessions created before metadata migration can include a bare path entry:

```json
{ "path": "src/room.asm" }
```

This is normalized on resume to:

```json
{ "path": "src/room.asm", "lines": 0, "chars": 0 }
```

## Structured `#kind:query` references

When a prompt references active-project game data with `#kind:query`, z3cli
resolves it against local project metadata before the model sees the turn.

Examples:

- `#room:0x45`
- `#room:glacia-estate`
- `#sprite:0x07`
- `#map:0x1A`

Current behavior:

- the frontend exposes a picker for project-backed `#` references when a local
  resource-label index is available
- resolved references are persisted in the transcript and restored on resume
- room, overworld, and message refs can add compact ROM context alongside the
  raw user prompt

## Protocol sync

Frontend transport types are generated from `z3cli/app/ipc_schema.py`:

```bash
cd frontend
npm run generate:protocol
```

That keeps `AttachmentMeta` and all `chat/message` fields aligned between backend
and `z3cli` client code.

## iOS remote (SwiftUI + bridge)

**Deploy to your iPhone:** [`docs/ios-zelda-remote/DEPLOY-TO-IPHONE.md`](docs/ios-zelda-remote/DEPLOY-TO-IPHONE.md) · [quickstart](docs/ios-zelda-remote/QUICKSTART-IPHONE.md)

Native Swift client and docs: [`docs/ios-zelda-remote/README.md`](docs/ios-zelda-remote/README.md), [`ios/ZeldaRemoteCore/`](ios/README.md). The wire protocol matches the Ink frontend ([`frontend/src/ipc/protocol.ts`](frontend/src/ipc/protocol.ts)).

Expose `z3cli --serve` over Tailscale/LAN with the optional WebSocket bridge:

```bash
pip install 'z3cli[bridge]'
export Z3CLI_BRIDGE_TOKEN='your-secret'
./scripts/run-ios-bridge.sh
```

Or manually: `python -m z3cli --bridge --bridge-host 0.0.0.0 --bridge-port 8765 --bridge-token "$Z3CLI_BRIDGE_TOKEN" -- --workspace ~/src/hobby/oracle-of-secrets`

Clients must send `Authorization: Bearer <token>` on the WebSocket handshake. One WebSocket session proxies to one child `z3cli --serve` process (see [`z3cli/app/ws_bridge.py`](z3cli/app/ws_bridge.py)).
