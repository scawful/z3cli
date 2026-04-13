# z3cli

`z3cli` is a model-first Zelda hacking CLI for local LM Studio or `llama.cpp`
models plus Zelda tool servers.

It is built to feel closer to a lightweight Claude Code session than a one-shot
prompt helper:

- interactive REPL
- quick model switching
- routing modes for Zelda specialists
- optional MCP tool calling
- LM Studio auto-load for local models
- optional `llama.cpp` fast-path backend for a pinned main model
- JSON-RPC serve mode for the Ink frontend (`z3ui`)

## Defaults

- chat registry: `~/src/lab/afs-scawful/config/chat_registry.toml`
- LM Studio MCP config: `~/.lmstudio/mcp.json`
- studio API base: `http://127.0.0.1:1234/v1`
- llama.cpp API base: `http://127.0.0.1:8080/v1`
- workspace: `~/src/hobby/oracle-of-secrets`
- ROM: `~/src/hobby/roms/oracle.sfc`

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
python3 -m z3cli --mode switchhook
python3 -m z3cli --model nayru
python3 -m z3cli --tools
python3 -m z3cli --backend llamacpp --llamacpp-model oracle-fast
```

## One-Shot Usage

```bash
python3 -m z3cli --mode oracle --prompt "Why does $420C not start DMA?"
python3 -m z3cli --mode switchhook --prompt "Generate a safe JSL hook for Link_Main"
python3 -m z3cli --mode oracle --prompt "Explain the BG3 tile upload path" --route-only
```

## Routing Modes

- `manual` - always use the active model alias
- `oracle` - use the `oracle` keyword router from the shared chat registry
- `switchhook` - send action-heavy prompts to `switchhook-act` and planning/debug prompts to `switchhook-plan`, with fallback to legacy Zelda experts
- `broadcast` - fan a prompt out to several model aliases and print each answer separately

Default broadcast set:

- `farore`
- `nayru`
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
- `/mode <manual|oracle|switchhook|broadcast>`
- `/modes`
- `/route <prompt>`
- `/broadcast <alias1,alias2,...>`
- `/load [name]`
- `/workspace <path>`
- `/rom <path|none>`
- `/tools <on|off>`
- `/reset [model|all]`
- `/exit`

## Notes

- `z3cli` keeps separate history per model, so switching from `nayru` to
  `farore` does not pollute specialist context.
- Auto-load is enabled by default. If a model is not loaded in LM Studio,
  `z3cli` will try `lms load <modelKey> --identifier <alias> --yes`.
- MCP servers are loaded from `~/.lmstudio/mcp.json` and filtered to the Zelda
  set by default: `afs`, `book-of-mudora`, `hyrule-historian`,
  `yaze-debugger`, and `yaze-editor`.
- When the workspace looks like a z3dk project, `z3cli` also exposes direct
  read-only `z3lsp` tools for diagnostics, hover, definition, symbol, and
  reference lookups.
