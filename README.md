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
- structured `@file` attachments
- sticky tool permissions
- post-write diff review plus verification hooks
- persistent shell commands
- LM Studio auto-load for local models
- optional `llama.cpp` fast-path backend for a pinned main model
- JSON-RPC serve mode for the Ink frontend (`z3ui`)

Current implementation status and recent work: [`docs/cli-current-state.md`](docs/cli-current-state.md)

## Defaults

- chat registry: `~/src/lab/afs-scawful/config/chat_registry.toml`
- LM Studio MCP config: `~/.lmstudio/mcp.json`
- studio API base: `http://127.0.0.1:1234/v1`
- llama.cpp API base: `http://127.0.0.1:8080/v1`
- workspace: `~/src/hobby/oracle-of-secrets`
- ROM: `~/src/hobby/roms/oracle.sfc`
- Public model portfolio note: [`docs/MODEL_PORTFOLIO_PUBLIC.md`](docs/MODEL_PORTFOLIO_PUBLIC.md)
- Halext experimental page draft: [`docs/halext-model-lab-draft.md`](docs/halext-model-lab-draft.md)

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

`z3cli` and `z3ui` start on `nayru` by default. Use `--model oracle` for
the canonical Oracle mainline and `--model oracle-fast` for the low-latency lane.

## One-Shot Usage

```bash
python3 -m z3cli --mode oracle --prompt "Why does $420C not start DMA?"
python3 -m z3cli --mode oracle --prompt "Generate a safe JSL hook for Link_Main"
python3 -m z3cli --mode oracle --prompt "Explain the BG3 tile upload path" --route-only
```

## Routing Modes

- `manual` - always use the active model alias
- `oracle` - canonical lane for local Zelda model work; legacy `oracle-main` aliases are accepted.
- `orchestrator` - use the portfolio router to pick a specialist or fall back to a safe specialist lane such as `nayru`
- `broadcast` - fan a prompt out to several model aliases and print each answer separately

Default broadcast set:

- `farore`
- `majora`
- `veran`

Override it like this:

```bash
python3 -m z3cli --mode broadcast --broadcast-models farore,majora,veran
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
- In `--serve` mode, write-like tools pause for diff review before the model
  continues. Accepted writes can automatically run repo-aware verification.
- The plain REPL now supports `/verify-hooks`, `/permissions`, and the
  persistent shell commands too, but diff review is still auto-accepted there.
- Auto-load is enabled by default. If a model is not loaded in LM Studio,
  `z3cli` will try `lms load <modelKey> --identifier <alias> --yes`.
- For fragile local LM Studio setups, `--no-auto-start-server --no-auto-load`
  keeps `z3cli` passive so it talks only to the server you started manually in
  the already-open LM Studio app.
- The default interactive startup model is `nayru`. `oracle` is the canonical
  entry and accepts `oracle-fast` as the lightweight fast lane.
- `oracle-main-plan`, `oracle-main-act`, `switchhook-plan`, `switchhook-act`,
  `switchhook`, and `oracle-tools` still resolve, but they are legacy aliases now.
- Do not repoint legacy aliases to fresh Qwen3 checkpoints until the replacement
  clears the ROM-hacking eval gate plus a live tool smoke run.
  ROM-hacking eval gate plus a live tool smoke run.
- The local rollout guard lives in `config/model_rollouts.toml`. If the chat
  registry points a protected alias at an unapproved `model_id`, z3cli refuses
  to route chats through that alias until the manifest is updated.
- MCP servers are loaded from `~/.lmstudio/mcp.json` and filtered to the Zelda
  set by default: `afs`, `book-of-mudora`, `hyrule-historian`,
  `yaze-debugger`, and `yaze-editor`.
- When the workspace looks like a z3dk project, `z3cli` also exposes direct
  read-only `z3lsp` tools for diagnostics, hover, definition, symbol, and
  reference lookups.

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
