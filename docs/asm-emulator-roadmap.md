# z3cli 65816 Authoring + Emulator Workflow Roadmap

This document lays out the implementation plan for turning `z3cli` from a
collection of low-level Zelda tools into a reliable 65816 authoring and test
loop.

The goal is not "more tools." The goal is a stable workflow where a model can:

1. inspect code and symbols
2. write or patch 65816 safely
3. assemble against a ROM without corrupting the working copy
4. run a controlled emulator scenario
5. assert behavior and capture evidence
6. recover cleanly on failure

## Current State

`z3cli` already has the main primitives:

- Unified bridge composition in `z3cli/app/tooling.py`
- `z3asm` assemble/lint and `z3disasm` bank export in
  `z3cli/protocol/z3asm_bridge.py`
- `z3ed` ROM and `mesen-*` emulator calls in `z3cli/protocol/z3ed_bridge.py`
- specialist adapters in `z3cli/core/tool_adapters/`
- post-write verification hooks in `z3cli/app/verify.py`
- request and tool timing telemetry in `z3cli/app/serve.py` and
  `z3cli/core/engine.py`

The current weakness is orchestration:

- assemble, run, and assert are separate calls
- emulator state is not wrapped in a transaction model
- MCP capability routing collapses too much into `reference`
- adapter tools are prose-friendly but not workflow-shaped
- verification hooks do not understand ASM edits
- telemetry is request-centric, not author-test-loop-centric

## Target Experience

The model-facing workflow should look like this:

1. inspect symbol context and existing code
2. generate or edit a patch file
3. call a single workflow tool such as `asm_patch_test`
4. receive structured results:
   - diagnostics
   - patched files or output paths
   - emulator setup summary
   - assertions passed and failed
   - CPU and memory snapshots
   - optional screenshot or breakpoint evidence
5. iterate until the scenario passes

The operator-facing workflow should look like this:

- accepted ASM writes automatically trigger lint and optional fast smoke tests
- named emulator scenarios are reusable from both REPL and `--serve`
- failures are actionable and reversible, not "the ROM is now in a weird state"

## Design Principles

- Prefer workflow tools over raw tool explosion.
- Make test execution transactional and reversible.
- Return structured JSON for machine decisions; render prose at the edge.
- Keep read-only/reference tools separate from mutation and emulator-control
  tools.
- Fail early when ROM path, socket path, test state, or toolchain pieces are
  missing.
- Record enough telemetry to tell whether the author-test loop is actually
  improving model behavior.

## Phases At A Glance

| Phase | Deliverable | Key files |
|-------|-------------|-----------|
| 0 | Shared workflow contracts and result schema | `z3cli/core/asm_workflow.py` (new), `tests/test_asm_workflow_contracts.py` (new) |
| 1 | MCP capability split for emulator and ROM controls | `z3cli/protocol/mcp_bridge.py`, `z3cli/app/tooling.py`, `tests/test_adapter_routing.py` |
| 2 | Transactional ROM and emulator session wrapper | `z3cli/protocol/asm_test_bridge.py` (new), `z3cli/core/rom_project.py`, new tests |
| 3 | High-level workflow tools: patch, run, assert | `asm_test_bridge.py`, adapter files, `tests/test_asm_test_bridge.py` (new) |
| 4 | ASM-aware verification hooks and REPL/serve affordances | `z3cli/app/verify.py`, `z3cli/app/repl.py`, `z3cli/app/serve.py`, `tests/test_verify_hooks.py` |
| 5 | Specialist surface rewrite around workflow tasks | `z3cli/core/tool_adapters/{din,farore,nayru,veran,majora}.py`, routing tests |
| 6 | Scenario presets and assertion packs | `config/` or `docs/` scenario manifests, workflow bridge, new tests |
| 7 | Workflow telemetry, evals, and rollout gates | `serve.py`, `shared_runtime.py`, `engine.py`, telemetry tests and docs |

## Phase 0: Contracts First

Before adding new bridge behavior, define the stable contract for author-test
workflow results.

### Deliverables

- A shared datamodel module for workflow inputs and results.
- A canonical JSON result envelope for all high-level 65816 testing tools.
- Normalized error categories.

### Proposed types

- `AsmPatchInput`
  - `patch_path`
  - `rom_path_override`
  - `scenario`
  - `frames`
  - `breakpoints`
  - `assertions`
  - `capture_screenshot`
  - `restore_after`
- `AsmPatchResult`
  - `ok`
  - `lint_ok`
  - `assemble_ok`
  - `emulator_ok`
  - `scenario_loaded`
  - `assertions`
  - `diagnostics`
  - `cpu`
  - `memory`
  - `breakpoint_hits`
  - `screenshot_path`
  - `artifacts`
  - `failure_stage`
  - `warnings`

### File targets

- New: `z3cli/core/asm_workflow.py`
- New: `tests/test_asm_workflow_contracts.py`

### Acceptance criteria

- All high-level tools serialize the same top-level keys.
- Tool results are easy to render in prose without losing structured detail.
- Errors distinguish setup failures from assemble failures from runtime failures.

## Phase 1: Split MCP Capability Routing

Right now `_build_capability_bridges()` in `z3cli/app/tooling.py` only promotes
`MCPBridge` into `reference`. That is too blunt because the default MCP set
includes emulator and editor-like servers.

### Problem

- `yaze-debugger` and `yaze-editor` are MCP-backed, but they are not routed as
  `emulator` or `rom`.
- Adapters therefore underuse available MCP tools.
- The model has no stable preference order across direct `z3ed` tools versus
  MCP tools that can do the same job better.

### Deliverables

- Capability inference for MCP tools based on owning server name.
- Ordered capability preference:
  - `emulator`: dedicated emulator bridge first, MCP debugger fallback
  - `rom`: z3ed ROM tools first, MCP editor fallback
  - `reference`: historian/book/afs/reference servers only
- Optional capability wrapper bridges if a single `MCPBridge` must expose
  multiple logical capabilities.

### File targets

- `z3cli/protocol/mcp_bridge.py`
- `z3cli/app/tooling.py`
- Possibly `z3cli/core/tool_bridge.py` if lightweight filtering wrappers help

### Tests

- Extend `tests/test_adapter_routing.py`
- New focused MCP routing tests if needed

### Acceptance criteria

- Adapters can target `emulator` and reach MCP debugger tools when direct mesen
  tools are unavailable.
- Reference-only adapters no longer accidentally see editor/debugger tools.

## Phase 2: Add Transactional ROM and Emulator Sessions

The current bridges are stateless per call. That is good for robustness, but
not enough for iterative patch testing.

### Deliverables

- A workflow bridge that owns a short-lived test transaction.
- Temporary ROM copy support for patch tests.
- Emulator snapshot and restore support where the backend allows it.
- Fallback cleanup behavior when snapshot restore is unavailable.

### Proposed behavior

1. Validate inputs and tool availability.
2. Create a temp ROM copy unless explicit in-place mutation is requested.
3. Optionally create or load a savestate / snapshot.
4. Assemble the patch against the temp ROM.
5. Launch or retarget the emulator backend to that ROM and scenario.
6. Run frames, breakpoints, and assertions.
7. Collect artifacts.
8. Restore emulator state and delete temp artifacts unless preservation is
   requested.

### File targets

- New: `z3cli/protocol/asm_test_bridge.py`
- `z3cli/core/rom_project.py`
- `z3cli/app/tooling.py`

### Tests

- New: `tests/test_asm_test_bridge.py`
- New: `tests/test_rom_transactions.py`

### Acceptance criteria

- Failed test runs do not leave the active ROM in an ambiguous state.
- Repeated workflow runs do not require manual emulator cleanup.
- Missing emulator ownership or socket setup yields immediate actionable errors.

## Phase 3: Add High-Level Workflow Tools

This phase introduces the actual tools the models should prefer.

### Initial tool set

- `asm_patch_test`
  - lint, assemble, run scenario, assert, capture evidence
- `hook_try`
  - specialized version for hook files and address-targeted validation
- `emu_assert`
  - run frames and check assertions against current state
- `scenario_run`
  - load a named scenario and collect state/screenshot output

### Assertion language

Support a small stable assertion vocabulary:

- memory equality and range checks
- register equality checks
- symbol-based checks when resolvable
- "no crash" / "PC not crash vector"
- breakpoint hit / not hit
- optional image or state invariants later

### File targets

- `z3cli/protocol/asm_test_bridge.py`
- `z3cli/app/tooling.py`
- `z3cli/core/tool_adapters/base.py` if richer structured dispatch helpers help

### Tests

- `tests/test_asm_test_bridge.py`
- adapter integration coverage

### Acceptance criteria

- Models can do a complete patch-test iteration with one primary tool call.
- The workflow tools return machine-usable JSON instead of markdown-only prose.

## Phase 4: Make Verification Hooks ASM-Aware

Post-write verification should understand Zelda assembly work, not just Python
and frontend edits.

### Deliverables

- Extend `select_verification_commands()` to detect `.asm`, `.inc`, linker
  config, and ROM tooling changes.
- Run `z3asm_lint` or a CLI equivalent after accepted ASM edits.
- Support optional fast scenario smoke tests after accepted writes.
- Surface workflow verification results in both REPL and `--serve`.

### Verification policy

- Fast default:
  - lint the changed ASM file
  - run at most one short scenario if configured
- Deep mode later:
  - matrix of scenarios for important patch areas

### File targets

- `z3cli/app/verify.py`
- `z3cli/app/repl.py`
- `z3cli/app/serve.py`

### Tests

- Extend `tests/test_verify_hooks.py`
- Add coverage for `.asm` edit detection and timeout cleanup

### Acceptance criteria

- Accepted ASM writes no longer skip validation.
- Verification failures clearly identify lint versus runtime breakage.

## Phase 5: Reshape Specialist Tool Surfaces

The current adapters are useful, but they mostly expose low-level or
explanation-heavy tools. The next pass should make each specialist good at a
specific part of the author-test loop.

### Proposed adapter roles

- `farore`
  - repro, breakpoint, quick scenario run, read state, assert current bug
- `din`
  - step trace, routine profiling, benchmark before/after, cycle-sensitive
    checks
- `veran`
  - patch-test, hook validation, ROM health, broader debugging synthesis
- `nayru`
  - symbol and routine explanation, docs, references, no mutation
- `majora`
  - subsystem mapping, usage tracing, conflict analysis, dependency surfacing

### Deliverables

- Replace some prose aggregation tools with workflow tools.
- Keep a smaller set of reference tools for context gathering.
- Update prompts or model notes if tool semantics change significantly.

### File targets

- `z3cli/core/tool_adapters/din.py`
- `z3cli/core/tool_adapters/farore.py`
- `z3cli/core/tool_adapters/veran.py`
- `z3cli/core/tool_adapters/nayru.py`
- `z3cli/core/tool_adapters/majora.py`

### Tests

- Extend `tests/test_adapter_routing.py`
- Add scenario-oriented adapter tests if needed

### Acceptance criteria

- Each specialist has a clear workflow identity.
- The orchestrator can pick specialists based on task phase, not vague flavor.

## Phase 6: Add Scenario Presets and Assertion Packs

Repeatable testing requires named scenarios, not improvised manual setup.

### Deliverables

- Scenario manifest format with:
  - name
  - description
  - ROM or state requirements
  - frames to run
  - default assertions
  - optional breakpoint set
- Support for reusable "assertion packs" such as:
  - `no_crash`
  - `room_loaded`
  - `player_control_restored`
  - `script_progressed`

### Storage options

- `config/asm_scenarios.toml`
- or `docs/` plus runtime loading if you want lower ceremony first

### Acceptance criteria

- Workflow tools can accept `scenario="room_load"` instead of raw setup flags.
- Repeated regressions can be encoded once and reused across models and evals.

## Phase 7: Add Workflow Telemetry and Evals

Request timing alone is not enough. We need author-loop telemetry.

### Metrics to record

- lint pass rate
- assemble pass rate
- scenario pass rate
- first-pass success rate
- mean iterations to green
- breakpoint hit frequency
- failure stage distribution
- average time per successful patch-test loop
- per-model success by tool profile and scenario

### Deliverables

- Workflow telemetry events emitted from the new bridge
- Aggregated counters in serve/runtime state
- JSON export suitable for eval dashboards and training data mining

### File targets

- `z3cli/core/engine.py`
- `z3cli/app/serve.py`
- `z3cli/app/shared_runtime.py`
- docs for telemetry fields

### Acceptance criteria

- You can tell whether a model is actually improving at 65816 patch work.
- Telemetry can feed future routing, eval gating, and training curation.

## Rollout Order

Recommended implementation order:

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7

This order matters:

- Phase 0 prevents schema churn.
- Phase 1 makes the capability graph honest.
- Phase 2 is the safety layer.
- Phase 3 is the first user-visible improvement.
- Phase 4 makes accepted writes safer immediately.
- Phase 5 through 7 are refinement and leverage.

## Suggested Milestones

### Milestone A: Foundation and Safety

Includes phases 0 through 2.

Success means:

- stable workflow result schema
- correct emulator and ROM capability routing
- transactional patch-test substrate exists

### Milestone B: First-Class Patch Testing

Includes phases 3 and 4.

Success means:

- `asm_patch_test` exists and works
- accepted ASM writes trigger meaningful validation
- the model can iterate without manual shell glue

### Milestone C: Model-Specific Optimization

Includes phases 5 through 7.

Success means:

- specialists have distinct loop roles
- named scenarios exist
- telemetry shows which models and tools are actually effective

## Non-Goals For The First Pass

- Full GUI automation ownership of arbitrary emulator instances
- Free-form visual regression as a gating requirement for every patch
- Replacing all raw tools with workflow tools
- Supporting every emulator backend equally on day one

The first pass should prefer one reliable path with fallback behavior over a
wide but brittle surface.

## Recommended First Three PRs

If this work is split into the next concrete PRs, the order should be:

1. `mcp-capability-split`
   - teach `z3cli` the difference between reference MCP, debugger MCP, and ROM
     editor MCP
2. `asm-workflow-bridge`
   - add transactional patch-test machinery and structured results
3. `asm-aware-verify-hooks`
   - automatically lint and smoke-test accepted ASM writes

That sequence gives the highest leverage with the least architectural churn.
