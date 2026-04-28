# z3cli

`z3cli` is a model-first Zelda hacking CLI for local LM Studio or `llama.cpp`
models plus Zelda tool servers.

It is built to feel closer to a lightweight Claude Code session than a one-shot
prompt helper:

- Ink terminal UI (`z3cli` and `z3ui` launch the same surface)
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

Service-first daemon/runtime plan: [`docs/daemon-runtime-plan.md`](docs/daemon-runtime-plan.md)

Experimental native router daemon (stdio JSON-RPC): build with
`cmake -S src/services/router/daemon_native -B src/services/router/daemon_native/build && cmake --build ...`
(see the daemon/runtime plan for details).

Current Zelda model training handoff: [`docs/HANDOFF_ZELDA_MODEL_WORK_20260425.md`](docs/HANDOFF_ZELDA_MODEL_WORK_20260425.md)

Shared agent harness contract: [`~/src/docs/guides/ai-coder/AGENT_HARNESS_CONTRACT.md`](../../docs/guides/ai-coder/AGENT_HARNESS_CONTRACT.md)

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
python3 -m pip install -e .
python3 -m z3cli
```

or through the installed console script:

```bash
z3cli
z3ui
```

From a checkout without installing, use `python3 -m z3cli`. Plain `z3cli`
launches the Ink UI. The Python backend still owns JSON-RPC serve mode and
scriptable control commands.

Useful variants:

```bash
python3 -m z3cli --mode oracle
python3 -m z3cli --model oracle
python3 -m z3cli --model nayru
python3 -m z3cli --tools
python3 -m z3cli --backend llamacpp --llamacpp-model oracle-fast
python3 -m z3cli route list
python3 -m z3cli route list advanced
python3 -m z3cli route smoke oracle-pro-ssh
python3 -m z3cli models catalog
python3 -m z3cli models loaded
z3ui --no-auto-start-server --no-auto-load --model oracle
```

Use `python3 -m z3cli --serve` for the backend protocol used by Ink, VSCode,
and the bridge. Use `python3 -m z3cli --legacy-repl` only when debugging the
old Python REPL directly.

`z3cli` and `z3ui` are operator-first. The canonical Oracle names stay stable,
and the default picker only shows installed local lanes from this contract:

- `oracle` -> `14B Oracle v8 · q4km` installed local default
- `din` -> installed Din optimizer v4
- `nayru` or `nayru-q8` -> installed Nayru explainer v9 q8_0
- `navi` (alias `farore`/`farore-q8`) -> installed Navi FIM/debug lane backed by Farore v5 q8
- `oracle-pro` -> advanced/manual alias for the installed Oracle-Pro v8 lane
- `oracle-fast`, `oracle-qwen35-9b`, and `oracle-mythic` -> configured lanes that stay hidden until their matching local artifacts are installed

Inside the normal chat flow, Oracle-family models now do hidden per-turn task
routing and light context prefetch automatically. In practice that means the
existing `Shift+Tab` chat mode can infer a rough Oracle task shape
(`trace`/`debug`/`author`, plus domain) and opportunistically preload compact
evidence such as register docs, symbol lookups, and one nearby disassembly
slice when the prompt strongly implies them.

The default local picker is intentionally small:

- `oracle` -> `Oracle 14B v8 · q4km`
- `din` -> `Din optimizer · installed v4`
- `nayru` or `nayru-q8` -> `Nayru explainer · installed v9 q8_0`
- `navi` (alias `farore`/`farore-q8`) -> `Navi FIM/debug · installed Farore v5 q8`

CLI `/models` and the main picker in `z3ui` show this operator list by
default. Use `models catalog advanced` for explicit heavy aliases such as
`oracle-pro`, raw Qwen fallbacks, quant variants such as `navi-q4km`, cloud
planners, and other manual lanes.

Host placement policy:

- primary local host is `medical-mechanica` on Windows + WSL2 with the RTX
  `5090`
- Mac is the control plane and fallback local machine
- local-first applies to `oracle`, `oracle-coder`, specialists, evals,
  merges, and most corrective work
- `14B` is also local-first now, with Vast fallback when the shared desktop is
  busy, unstable, or needed for work/gaming
- `oracle-pro` can delegate heavier work to hidden vLLM sidecars:
  `oracle-coder-pro` for Qwen3-Coder 30B-A3B patch synthesis and
  `oracle-reasoner-27b` for Qwen3.6 27B model/catalog/training strategy
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
/route oracle-pro-vast
```

The hidden Oracle sidecars use vLLM-compatible OpenAI endpoints. Start them
only when you want the heavier delegated paths:

```bash
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 \
  --served-model-name oracle-coder-pro \
  --port 18081 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90

vllm serve Qwen/Qwen3.6-27B-FP8 \
  --served-model-name oracle-reasoner-27b \
  --port 18082 \
  --max-model-len 32768 \
  --reasoning-parser qwen3 \
  --language-model-only \
  --gpu-memory-utilization 0.90
```

The eval-first training path for these sidecars is tracked in
[`docs/oracle-sidecar-eval-training-path-20260425.md`](docs/oracle-sidecar-eval-training-path-20260425.md).

Named LM Studio nodes now work the same way for the Windows home box:

```bash
/studio-nodes
/studio-node oracle-pro-home
/backend studio
```

Shortcut:

```text
/route oracle-pro-5090
/route oracle-pro
```

`/route oracle-pro-5090` carries both the tunneled LM Studio API base and the
tunneled `afs-hostd` control URL, so Oracle auto-load works even if you did not
export `AFS_HOSTD_URL` before launching `z3cli`. Legacy `/use home` still maps
to the same route.

`/route list` is the operator view: it shows canonical routes such as
`oracle-pro-5090`, `oracle-pro-ssh`, and `oracle-pro-vast` with old aliases
collapsed. Use `/route list advanced` when you want raw registry nodes and
model fallback targets.

If local port forwarding is unavailable but SSH to `medical-mechanica` works,
use the SSH command-proxy node instead:

```text
/route oracle-pro-ssh
```

That path talks to the Windows LM Studio OpenAI API through SSH without
opening `ssh -L` tunnels. It expects `oracle-pro` v8 to already be loaded on
the Windows host and returns complete responses rather than token streaming.
Probe the route from inside `z3cli` with:

```text
/route smoke oracle-pro-ssh
```

or from a non-interactive shell:

```bash
python3 -m z3cli route smoke oracle-pro-ssh
python3 -m z3cli --smoke home-ssh
```

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

- `navi`
- `nayru`
- `din`

Override it like this:

```bash
python3 -m z3cli --mode broadcast --broadcast-models navi,nayru,din
```

## Interactive Commands

- `/help`
- `/status`
- `/backend [name]`
- `/route [list [advanced|--all]|target|smoke [target]|health [target]|preview <prompt>]`
- `/use [target]` (legacy alias for `/route <target>`)
- `/backends`
- `/backend-status`
- `/smoke [target]`
- `/models [list|catalog [advanced|--all]|loaded|routes [advanced|--all]]`
- `/loaded`
- `/servers`
- `/model <name>`
- `/specialist <din|navi|nayru>`
- `/mode <manual|oracle|orchestrator|broadcast>`
- `/modes`
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
  `navi` does not pollute specialist context.
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
- In the Ink UI (`z3cli`/`z3ui` backed by `--serve`), write-like tools pause
  for diff review before the model continues. Accepted writes can automatically
  run repo-aware verification.
- The legacy Python REPL is still available with `--legacy-repl` for debugging,
  but it is not the default chat surface.
- Auto-load is enabled by default. If a model is not loaded in LM Studio,
  `z3cli` will try `lms load <modelKey> --identifier <alias> --yes`.
- `z3ui` now surfaces concurrently loaded models plus LM Studio-reported loaded
  size, and `/unload` can evict one model or all loaded LM Studio models.
- For fragile local LM Studio setups, `--no-auto-start-server --no-auto-load`
  keeps `z3cli` passive so it talks only to the server you started manually in
  the already-open LM Studio app.
- `oracle` is the canonical daily local Oracle entry and points at the installed
  `14B Oracle v8 · q4km` GGUF on the Windows host.
- `oracle-fast` is the lower-latency corrective Oracle slot, but it stays hidden
  until the matching local GGUF is restored.
- `oracle-q8` and the direct `qwen3-oracle-8b` entry expose the same corrective
  Oracle model as `8B corrective Oracle · q8_0`.
- `oracle-pro` is an advanced/manual alias for the same current `14B Oracle-Pro
  v8 · q4km` critical-safe local lane.
- `oracle-mythic` is the manual-only `27B switchhook Oracle · q4km` model and
  should stay an explicit opt-in, not the default local path.
- `qwen3-oracle-14b` is a reserved local catalog slot for the current 14B
  Oracle mainline training target. It stays hidden until a matching LM Studio
  install exists.
- `oracle-coder` remains internal and spawn-only; it is meant to be delegated
  to by Oracle-family parents, not selected as a normal top-level working model.
- `oracle-coder-pro` and `oracle-reasoner-27b` are hidden vLLM sidecars for
  Oracle-family delegation. They stay out of the picker but appear in
  `spawn_subagent` when the matching endpoints are configured.
- `navi` (formerly `farore`) and `nayru` are the live local specialists.
  `navi-q4km` remains available through the advanced catalog for lighter quant
  testing when that artifact is installed. Legacy
  `farore` / `farore-q4km` / `farore-q8` aliases still resolve to the
  matching navi entry for one release.
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

Frontend transport types are generated from `src/app/ipc_schema.py`:

```bash
cd frontend
npm run generate:protocol
```

That keeps `AttachmentMeta` and all `chat/message` fields aligned between backend
and `z3cli` client code. The same generator also writes
`extensions/vscode-z3cli/src/ipc/protocol.generated.ts` and refreshes the
extension's command catalog copy, so the VSCode extension stays in lock-step.

Protobuf contracts are linted with protolint:

```bash
brew install protolint
protolint lint proto
python3 -m pytest -q tests/test_proto_contracts.py
```

## VSCode / Cursor / Antigravity extension

`extensions/vscode-z3cli/` is a VSCode-API extension that surfaces the same
chat, slash commands, and routes inside the editor and adds inline FIM
autocomplete. It spawns `python -m z3cli --serve` per workspace and exchanges
NDJSON JSON-RPC over stdio. FIM hits `/v1/completions` directly on LM Studio
or llama.cpp; if the local server isn't loaded, the extension falls back to
the new `complete` JSON-RPC method which auto-loads the model.

```bash
cd extensions/vscode-z3cli
npm install
./scripts/package-vsix.sh
./scripts/install-vsix.sh   # installs into VSCode, Cursor, Antigravity
```

Details and settings: [`extensions/vscode-z3cli/README.md`](extensions/vscode-z3cli/README.md).

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

Clients must send `Authorization: Bearer <token>` on the WebSocket handshake. One WebSocket session proxies to one child `z3cli --serve` process (see [`src/app/ws_bridge.py`](src/app/ws_bridge.py)).
