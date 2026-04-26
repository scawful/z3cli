# Oracle Adapter Plan

Status: implemented
Owner: scawful
Date: 2026-04-20

## Why

The qwen3-oracle-14b-v1 r3 capability eval failed 10 / 12 grounded cases. The
failure modes are almost entirely "didn't recall a specific symbol or register"
or "invented an address." Both are lookup problems, not parameter-count
problems:

- `oracle_main_songbank_blackout` — missed `Underworld_LoadSongBankIfNeeded` at `$0088EC`
- `oracle_main_applygraphicssheet_dma` — missed `$2116`, `$4300`, `$420B`
- `oracle_main_mdmaen_vs_hdmaen` — confused MDMAEN ($420B) with HDMAEN ($420C)
- `oracle_main_jsr_rtl_mismatch` — missed JSR/RTL pairing tokens
- `oracle_main_do_not_invent_symbols` — invented references

Each of these is one tool call away from a correct answer if the model has
read-only access to the disassembly index, ROM/WRAM, and a small SNES register
reference.

## What Already Exists

z3cli already has the substrate. No new bridge needed.

| Capability | Bridge | Concrete primitives in use today |
|------------|--------|----------------------------------|
| `symbols`  | z3lsp  | `z3lsp_symbols`, `z3lsp_definition`, `z3lsp_references`, `z3lsp_diagnostics` |
| `rom`      | z3ed   | `dungeon_*`, `message_search`, others |
| `emulator` | z3ed mesen-* | `mesen_memory_read`, `mesen_disasm`, `mesen_cpu`, `mesen_gamestate`, `mesen_breakpoint`, `mesen_control` |
| `workspace`| files  | `workspace_read` |
| `reference`| MCP    | `consult_reference`, `find_usages`, `memory.search` |

Existing per-specialist adapters all sit in `src/core/tool_adapters/` and use
`_call_on(capability, tool, args)` against this substrate.

## Current State

`oracle`, `oracle-fast`, and `oracle-pro` are registered in
`ADAPTER_REGISTRY` and use `OracleAdapter` instead of the full unfiltered MCP
surface. The adapter exposes a compact read-only surface, while the full
profile remains available to models explicitly configured for it.

Runtime Oracle prefetch also preserves failed grounding results. If a register,
symbol, disassembly, or workspace lookup is unavailable, the prompt now carries
that failure forward instead of silently dropping it and encouraging an answer
from weights alone.

## Implemented Tool Surface

| Adapter tool | Underlying primitive(s) | Targets failure ID(s) |
|--------------|-------------------------|------------------------|
| `label_lookup(query)` | `("symbols", "z3lsp_symbols", {"query": q})` | `songbank_blackout`, `do_not_invent_symbols` |
| `grep_disasm(query)`  | `("symbols", "z3lsp_symbols")` + `("symbols", "z3lsp_references")` | `applygraphicssheet_dma`, `jsr_rtl_mismatch` |
| `rom_read(address, length)` | `("emulator", "mesen_memory_read", {"address": a, "length": n})` | `darkroom_capture_first` |
| `disasm_at(address, count)` | `("emulator", "mesen_disasm", {"address": a, "count": n})` | `applygraphicssheet_dma`, `torch_loop_width` |
| `cpu_state()` | `("emulator", "mesen_cpu", {})` + `("emulator", "mesen_gamestate", {})` | `darkroom_capture_first`, `jumptablelocal_guard` |
| `register_doc(name_or_addr)` | static lookup against a compact SNES register table | `mdmaen_vs_hdmaen`, `applygraphicssheet_dma`, `stz_long_address` |
| `workspace_read(path, max_lines)` | `("workspace", "workspace_read", {"path": p, "max_lines": n})` | source/layout questions, code-content grounding |

`register_doc` is the only one whose data does not live behind an existing
bridge. It uses a static table mapping common SNES MMIO addresses
(`$2100`-`$21FF`, `$4200`-`$43FF`) to short prose, shipped under
`src/core/tool_adapters/data/snes_registers.json`.

### Wiring

1. `src/core/tool_adapters/oracle.py` defines the read-only adapter.
2. `src/core/tool_adapters/data/snes_registers.json` ships the static
   register table.
3. `tool_adapters/__init__.py` registers:
   ```python
   "oracle": OracleAdapter,
   "oracle-fast": OracleAdapter,
   "oracle-pro": OracleAdapter,
   ```
4. `runtime.py` binds adapter profiles automatically for matching models.
5. `WRITE_TOOLS = frozenset()` keeps this adapter read-only.

### Subagent path

Nested subagent delegation exists in both serve and REPL paths. Oracle-family
parents can expose `spawn_subagent` to delegate focused coding work to
`oracle-coder`, heavier Oracle-Pro authoring to `oracle-coder-pro`, and
long-context model/catalog/training analysis to `oracle-reasoner-27b`; child
agents inherit the same model-aware bridge wrapping and Oracle adapter behavior
as top-level local-model runs.

## Validation Plan

Before relying on a new model/checkpoint:

1. Dry-run each tool against a real Mesen socket and a checked-out
   `oracle-of-secrets` workspace. Confirm `label_lookup("$0088EC")` returns
   `Underworld_LoadSongBankIfNeeded` and `register_doc("$420B")` returns the
   MDMAEN one-liner.
2. Re-run the capability eval against `qwen3-oracle-8b-v1` with the OracleAdapter
   active. Compare bucket pass rates against the no-adapter baseline.
3. The win condition is movement on `hardware_register_grounding` (currently
   0/2 mean 0.475) and `oracle_docs_and_system_reasoning` (currently 1/2 mean
   0.625). DPO + tools should compound on those buckets.

## Out of Scope

- Write tools (room edits, hooks, patches). Adapter stays read-only; existing
  full-surface profiles handle writes.
- Live emulator control (step, breakpoint set). `cpu_state` reads only;
  control surface stays with `veran` / `farore` who already do debug work.
- New MCP servers. This plan reuses the existing capability bridges only.
