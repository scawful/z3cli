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

- chat registry: `config/chat_registry.toml`
- LM Studio MCP config: `~/.lmstudio/mcp.json`
- studio API base: `http://127.0.0.1:1234/v1`
- llama.cpp API base: `http://127.0.0.1:8080/v1`
- workspace: `~/src/hobby/oracle-of-secrets`
- ROM: `~/src/hobby/roms/oracle.sfc`
- Public model portfolio note: [`docs/MODEL_PORTFOLIO_PUBLIC.md`](docs/MODEL_PORTFOLIO_PUBLIC.md)
- Halext experimental page draft: [`docs/halext-model-lab-draft.md`](docs/halext-model-lab-draft.md)
- Internal RL threshold policy: [`docs/ZELDA_RLHF_THRESHOLD_POLICY.md`](docs/ZELDA_RLHF_THRESHOLD_POLICY.md)
- override registry with `--registry /path/to/chat_registry.toml` or `Z3CLI_REGISTRY`

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

`z3cli` and `z3ui` now keep the main Oracle contract intentionally small:

- `oracle-fast` -> `8B corrective Oracle · q4km` pinned daily local model
- `oracle` -> reserved mainline slot hidden until installed
- `oracle-pro` -> `14B Oracle-Pro · q4km` current local pro lane
- `oracle-mythic` -> `27B switchhook Oracle · q4km` manual heavy model

Inside the normal chat flow, Oracle-family models now do hidden per-turn task
routing and light context prefetch automatically. In practice that means the
existing `Shift+Tab` chat mode can infer a rough Oracle task shape
(`trace`/`debug`/`author`, plus domain) and opportunistically preload compact
evidence such as register docs, symbol lookups, and one nearby disassembly
slice when the prompt strongly implies them.

Everything else stays available in the catalog / alternate tabs:

- `qwen3-oracle-8b` or `oracle-q8` -> `8B corrective Oracle · q8_0`
- `nayru` or `nayru-q8` -> `9B Qwen3.5 explainer · q8_0`
- `farore` or `farore-q8` -> `9B Qwen3.5 debug/FIM · q8_0`
- `farore-q4km` -> `9B Qwen3.5 debug/FIM · q4km`
- `majora` or `majora-q4km` -> `9B Qwen3.5 architecture · q4km`
- `hylia` or `hylia-q8` -> `9B Qwen3.5 lore/history · q8_0`
- `hylia-q4km` -> `9B Qwen3.5 lore/history · q4km`

CLI `/models` shows that wider visible specialist bench again, while the main
picker in `z3ui` stays focused on the primary Oracle contract. Use the model
manager tabs in `z3ui` when you want the wider bench or base-Qwen catalog.

Host placement policy:

- primary local host is `medical-mechanica` on Windows + WSL2 with the RTX
  `5090`
- Mac is the control plane and fallback local machine
- local-first applies to `oracle-fast`, `oracle-coder`, specialist `9B`, evals,
  merges, and most corrective work
- `14B` is also local-first now, with Vast fallback when the shared desktop is
  busy, unstable, or needed for work/gaming
- `scawfulbot` and Oracle-family inference may share that box, so repeated or
  conflict-heavy workloads can be paused, throttled, or offloaded

Use `/orchestrator <model|auto>` in `z3ui` when you want to pin or clear the
cloud planner.

## Windows 5090 Serving

When `medical-mechanica` is the active LM Studio host, treat the API path and
the control path separately.

Preferred control path: `afs-hostd`

1. Open local tunnels to the Windows LM Studio API and host daemon:

```bash
bash ../lab/afs-scawful/scripts/tunnel_windows_hostd.sh --background
bash scripts/tunnel_windows_lmstudio.sh --background
```

2. Point `z3cli` at the tunneled API and host daemon:

```bash
export AFS_HOSTD_URL="http://127.0.0.1:8766"
export LMSTUDIO_BASE_URL="http://127.0.0.1:2234/v1"
```

Fallback only, when `afs-hostd` is not running:

```bash
export Z3CLI_LMSTUDIO_REMOTE_HOST="medical-mechanica"
export Z3CLI_LMSTUDIO_REMOTE_ENDPOINT="http://127.0.0.1:1234/v1"
export Z3CLI_LMSTUDIO_REMOTE_LMS_PATH="C:\\Users\\scawful\\.lmstudio\\bin\\lms.exe"
```

With `AFS_HOSTD_URL` set, the studio backend keeps using the local API base you
provide for inference, but `/backend-status`, `/loaded`, `/load`, `/unload`,
and inventory checks go through the Windows host API instead of assuming a
local Mac LM Studio CLI. The older `Z3CLI_LMSTUDIO_REMOTE_HOST` path still
works as a fallback, but it is no longer the preferred control plane.

For temporary remote `oracle-pro` testing while away from the home box, use the
dedicated Vast helper from the training repo:

```bash
bash ../training/scripts/serve_oracle_pro_vast.sh start --vast-host <host> --vast-port <port>
```

Then open the printed SSH tunnel and point `z3cli` / `z3ui` at the tunneled
`llama.cpp` endpoint:

```bash
export LLAMACPP_BASE_URL="http://127.0.0.1:18080/v1"
python3 -m z3cli --backend llamacpp --llamacpp-model oracle-pro
z3ui --backend llamacpp --llamacpp-model oracle-pro --llamacpp-api-base "$LLAMACPP_BASE_URL"
```

Named `llama.cpp` nodes now live in `config/chat_registry.toml`, so you can
keep one local endpoint plus one or more tunneled remote endpoints and switch
them without re-exporting env vars every time:

```bash
/llamacpp-nodes
/llamacpp-node oracle-pro-vast
/backend llamacpp
```

Shortcut:

```text
/use vast
```

Named LM Studio nodes now work the same way for the Windows home box:

```bash
/studio-nodes
/studio-node oracle-pro-home
/backend studio
```

Shortcut:

```text
/use home
/use oracle-pro
```

`/use home` now carries both the tunneled LM Studio API base and the tunneled
`afs-hostd` control URL, so Oracle auto-load works even if you did not export
`AFS_HOSTD_URL` before launching `z3cli`.

The same host daemon now also exposes WSL runtime status for the Windows `5090`
box. The training-side control script uses the same tunnel:

```bash
export AFS_HOSTD_URL="http://127.0.0.1:8766"
python3 ../training/scripts/windows_zelda_ctl.py wsl-status
python3 ../training/scripts/windows_zelda_ctl.py wsl-envs
python3 ../training/scripts/windows_zelda_ctl.py status --task qwen35-oracle-fast-v2 --config configs/zelda/qwen35_oracle_fast_v2.toml
```

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
- `/use [target]`
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
- `oracle-fast` is the canonical daily local Oracle entry and points at the
  smaller `8B corrective Oracle · q4km` model.
- `oracle-q8` and the direct `qwen3-oracle-8b` entry expose the same corrective
  Oracle model as `8B corrective Oracle · q8_0`.
- `oracle` is the reserved mainline slot and stays hidden until a matching local
  install exists.
- `oracle-pro` is the current `14B Oracle-Pro · q4km` local pro lane.
- `oracle-mythic` is the manual-only `27B switchhook Oracle · q4km` model and
  should stay an explicit opt-in, not the default local path.
- `qwen3-oracle-14b` is a reserved local catalog slot for the current 14B
  Oracle mainline training target. It stays hidden until a matching LM Studio
  install exists.
- `oracle-coder` remains internal and spawn-only; it is meant to be delegated
  to by `oracle`, not selected as a normal top-level working model.
- `farore`, `hylia`, `majora`, and `nayru` now point at the live local Qwen3.5
  9B exports, with q4km sidecars exposed where you have them.
- Legacy `oracle-main*` and `oracle-tools` names still resolve quietly for
  compatibility; `switchhook*` now resolve through `oracle-mythic`.
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
