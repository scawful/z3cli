# z3cli Orchestration Architecture

This document captures the 9-phase expansion that took z3cli from a single-model
local chat harness into a multi-provider, multi-agent orchestration system with
context management and cost controls.

The work was scoped around one question: how do we keep local fine-tuned
Zelda specialists doing what they're good at while letting cloud frontier models
plan and synthesize across them?

## Phases at a glance

| Phase | Deliverable | Key files |
|-------|-------------|-----------|
| 1 | Provider abstraction | `src/core/provider.py` |
| 2 | Subagent runner + bridge | `src/core/subagent.py`, `subagent_bridge.py` |
| 3 | Orchestrator mode | `src/app/runtime.py` (`ORCHESTRATOR_MODE`) |
| 4 | Context compaction | `src/core/compaction.py` |
| 5 | Frontend rendering | `frontend/src/components/SubagentPanel.tsx`, `utils/subagentState.ts` |
| 6 | Prompt caching | `AnthropicProvider._build_system`, `_convert_tools` |
| 7 | Deferred tool loading | `src/core/deferred_tools.py` |
| 8 | Nested subagents | `SubagentRunner` depth + cycle detection |
| 9 | Cache hit rate badge | `frontend/src/utils/cacheMetrics.ts` |

Final test totals: **108 Python tests**, **45 frontend tests**, TypeScript clean.

---

## 1. Provider abstraction

Before: `ChatEngine` talked directly to an OpenAI-compatible endpoint via httpx.
The wire format was baked into the engine's streaming loop.

After: a `Provider` protocol (`stream()`, `check_connection()`, `close()`)
separates wire format from the tool-calling loop.

**Implementations:**
- `LocalProvider` — wraps LM Studio / llama.cpp / Ollama SSE streaming
- `AnthropicProvider` — talks to Claude API with native thinking blocks and
  `tool_use` content blocks
- `OpenAICloudProvider` — GPT-4o, o3, etc. (delegates to LocalProvider's SSE
  parser since the wire format is compatible)

**Key data types** (in `src/core/provider.py`):
- `CompletionRequest` — provider-agnostic request shape
- `CompletionChunk` — streaming chunk with content / tool_calls / usage
- `ContentDelta` — text/thinking/reasoning split
- `ToolCallDelta` — accumulated tool call id+name+arguments
- `UsageInfo` — prompt / completion / cache_creation / cache_read

**Model config** gained `provider`, `api_base`, `api_key_env`, `is_cloud`,
`is_local`, `resolve_api_key()`.

---

## 2. Subagent runner + bridge

**Why:** Let the main model delegate subtasks to specialists running in
isolated contexts. Two paths were built:

1. **User-driven** — `/subagent <model> <prompt>` command
2. **Model-driven** — `spawn_subagent` tool on `SubagentBridge`

**Runner** (`src/core/subagent.py`):
- `SubagentConfig` — name, model, task prompt, tool_profile, max_rounds
- `SubagentResult` — text, thinking, tool_call count, tokens, error/cancelled
- Lifecycle events: start, text, thinking, tool_call, tool_result, done, error
- `spawn()` creates a fresh `ChatEngine` with its own history, returns result
- `spawn_many()` for parallel execution

**Bridge** (`src/core/subagent_bridge.py`):
- Exposes `spawn_subagent(model, prompt, tool_profile?, max_rounds?)` and
  `list_subagents()` as OpenAI-style tools
- Composed with the main tool bridge via `CompositeBridge` when
  `ServeState.subagent_tools_enabled`

**IPC:** seven `subagent/*` JSON-RPC notifications stream subagent activity to
the frontend (phase 5 rendered them).

---

## 3. Orchestrator mode

A dedicated routing mode where a cloud planner drives the flow. `orchestrator`
is available alongside `manual`, `oracle`, and `broadcast` (legacy `oracle-main`
is accepted as a router alias for `oracle`).

**What it does:**
1. Routes to the configured orchestrator model (preferred tag → candidate list
   → first cloud model with a key → fallback to active model)
2. Forces `SubagentBridge` composition so the planner always sees
   `spawn_subagent` + `list_subagents`
3. Prepends `build_orchestrator_prompt(specialists)` to the system prompt —
   gives the planner a catalog of available specialists with roles and tool
   profiles

**Commands:** `/mode orchestrator`, `/orchestrator [model|auto]`,
`/subagent-tools on|off`.

**CLI flag:** `--orchestrator <model>`.

The model then decides when to delegate, can spawn specialists in parallel,
and synthesizes their outputs into a coherent response.

---

## 4. Context compaction

Local specialists have small context windows (4K–32K). Long tool-heavy
conversations exhaust them. Rather than manual `/reset`, compaction
auto-summarizes older turns while preserving the system prompt and recent
turns verbatim.

**`ConversationCompactor`** (`src/core/compaction.py`):
- `CompactionPolicy` — `context_budget`, `threshold_ratio` (0.75), `keep_recent_turns` (3)
- `estimate_tokens()` / `estimate_messages_tokens()` — ~3.7 chars/token heuristic
  (biased up for tool JSON). No tokenizer dependency.
- `ProviderSummarizer` runs any Provider against a structured-recap prompt
  that preserves decisions, tool outcomes, files/symbols touched, TODOs, user
  preferences — NOT narrative filler.

**Integration:**
- `ChatEngine.chat()` auto-runs compaction before appending the new user message
  when `should_compact()` returns True
- Emits `CompactionEvent` → serve.py forwards as `context/compacted` IPC
  notification + visible system message in transcript
- `ModelConfig.context_budget` — 0 disables, positive enables
- `/compact [model]` for manual trigger
- Compaction failures are non-fatal — emits a warning and continues with
  uncompacted history

---

## 5. Frontend rendering

The `subagent/*` and `context/compacted` notifications from phases 2 and 4
were streaming but nothing rendered them. Phase 5 closed the loop.

**Pure reducer** (`frontend/src/utils/subagentState.ts`):
- `applySubagentEvent(entries, event, now)` handles all 7 lifecycle events
- `pruneFinishedSubagents()` drops completed rows (auto-called at turn start)
- React-free so the logic is unit-testable independent of Ink

**Component** (`frontend/src/components/SubagentPanel.tsx`):
- One bordered row per subagent with spinner/✓/✗/⊘ status indicator
- Model-colored name, elapsed time, tool count, active tool, last-N-lines preview
- Header shows running count + total count

**Hook wiring** (`frontend/src/hooks/useBackend.ts`):
- New state: `subagents`, `lastCompaction`, `clearFinishedSubagents`
- Event switch handles all subagent methods + `context/compacted`
- Auto-prune on `sendMessage`; reset on `replaceMessages`

---

## 6. Anthropic prompt caching

Orchestrator mode sends a huge system prompt (harness context + specialist
catalog) on every turn. Without caching, every request pays full input-token
cost. Phase 6 wired `cache_control` markers through the Anthropic payload so
subsequent requests read at ~10% of input cost.

**Provider changes:**
- `CompletionRequest.prompt_cache: bool = True` (per-request hint)
- `AnthropicProvider._build_system(system, prompt_cache)` — wraps system in a
  content block with `cache_control: {type: "ephemeral"}` when enabled
- `AnthropicProvider._convert_tools(tools, prompt_cache)` — marks the last tool
  with `cache_control` so the whole tool list becomes a cacheable prefix

**Plumbing:**
- `DoneEvent` gains `cache_creation_tokens` and `cache_read_tokens`
- `ServeState` tracks session totals; persisted through session metadata
- Frontend protocol + `useBackend` expose the counts to React state
- `ModelConfig.prompt_cache: bool = True` — toggle per-model

**Cost math:** with a 3000-token stable prefix over 10 orchestrator requests,
roughly **79% savings** on input costs for the cached portion.

---

## 7. Deferred tool schema loading

For models using `tool_profile = "*"` (full MCP surface), all 30+ tool schemas
ship in every request. Phase 7 adds a `tool_search` meta-tool that reveals
schemas on demand — the model discovers tools it needs without carrying the
full catalog in every prompt.

**`DeferredToolBridge`** (`src/core/deferred_tools.py`):
- Wraps any `ToolBridge`, exposes only `tool_search` + configurable `core` set
- Search scores name matches 3× description matches, returns top N with full
  schemas, adds them to `_revealed` set
- Subsequent `get_openai_tools()` includes revealed tools
- Calling an un-revealed tool returns helpful "call tool_search first" error

**Engine change:** moved `tools = self.bridge.get_openai_tools()` INSIDE the
round loop (was one-time fetch) so newly-revealed tools become callable on
the next request without re-instantiating the engine.

**Config:**
- `ModelConfig.deferred_tools: bool = False` (opt-in)
- `ModelConfig.core_tools: list[str]` — always-visible tools

**Wrap order:** `[tool_profile adapter] → [DeferredToolBridge] → [ReadOnlyBridge]`

---

## 8. Nested subagent delegation

Initially only the top-level model could spawn subagents; subagents were leaves.
Phase 8 lets any subagent itself delegate further, bounded by a depth cap and
cycle detection.

**Config:** `SubagentConfig.depth` + `parent_chain: list[str]`.

**Runner:** `SubagentRunner.__init__` gains `max_depth=2`, `models=None`,
`expose_subagent_bridge_to_children=True`. `spawn()`:
1. Rejects `config.depth > max_depth` with structured error
2. Rejects cycles (`config.model.name` in `config.parent_chain`)
3. Strips inherited subagent bridges from the child's base tool surface, then
   composes a fresh nested `SubagentBridge(current_depth=depth, parent_chain=[...], parent_model=...)`
   onto the child's effective bridge via a new `CompositeBridge`

**Bridge:** `SubagentBridge` gained keyword-only `current_depth`,
`parent_chain`, `parent_model` so it can track its own position in the tree.

**Why it's safe:**
- Depth cap defaults to 2 (3 levels total)
- Cycle detection prevents `nayru → farore → nayru`
- Errors propagate as `SubagentResult.error`, not raises — parent sees
  structured failure

---

## 9. Cache hit rate badge

The cache tokens from phase 6 were tracked in frontend state but not rendered.
Phase 9 surfaces them in the StatusBar with a compact muted badge.

**Helpers** (`frontend/src/utils/cacheMetrics.ts`):
- `cacheHitRate(read, creation): number` — fraction in [0, 1], zero-guard
- `formatCacheCompact(read, creation): string` — `""` / `"caching on · 1.2k cached"` / `"94% hit · 12k cached"`
- `estimatedSavingsCents(read, creation, normalInputTokens, pricePerMInput=3.0)` — exported for future use

**StatusBar integration:** renders `{rupee} {formatCacheCompact(...)}` in
`colors.muted` after the token counter. Hidden when no cache activity.

---

## Cross-cutting architecture

### Layering

```
Frontend (Ink/React)
  └─ useBackend hook
       └─ JSON-RPC over stdio
            └─ serve.py (ServeState)
                 ├─ SubagentRunner
                 ├─ Session (JSONL)
                 └─ per-model ChatEngine
                      ├─ Provider (Local / Anthropic / OpenAI)
                      ├─ ConversationCompactor (optional)
                      └─ ToolBridge
                           ├─ ToolAdapter (profile: din/nayru/...)
                           ├─ DeferredToolBridge (optional)
                           ├─ ReadOnlyBridge (write gate)
                           ├─ MCPBridge (spawned MCP servers)
                           ├─ Z3LspBridge (z3lsp subprocess)
                           └─ SubagentBridge (spawn_subagent tool)
```

### Bridge composition rules

- Multiple bridges merge via `CompositeBridge`; name collisions get
  server-prefixed
- Wrap order when building effective per-model bridge:
  `[tool_profile adapter] → [DeferredToolBridge] → [ReadOnlyBridge]`
- Subagent bridge composes side-by-side with the main bridge, not on top

### Registry fields used across phases

```toml
[[models]]
name = "..."
model_id = "..."
provider = "studio"       # phase 1
tool_profile = "*"         # (pre-existing)
api_key_env = "..."        # phase 1 (cloud only)
prompt_cache = true        # phase 6 (cloud only)
context_budget = 8192      # phase 4
deferred_tools = false     # phase 7
core_tools = []            # phase 7
```

---

## Potential future improvements

Ideas worth considering, roughly ordered by perceived value-vs-effort.

### Near-term polish

1. **Token cost widget** — `estimatedSavingsCents` is already exported and
   tested but never rendered. A `/cost` command or StatusBar line that shows
   "Session cost: $0.12 (saved $0.48 via caching)" would close the loop.

2. **Depth indicator in SubagentPanel** — when nested subagents spawn, the UI
   just shows a flat list. Indent by `entry.depth` (after threading it through
   the IPC notification) so the tree structure is visible.

3. **Compaction trigger preview** — before compaction fires automatically, emit
   a notification showing the model what will be dropped. Lets the user `/cancel`
   compaction and manually curate if they disagree with the heuristic.

4. **Tool search memoization** — `DeferredToolBridge._handle_search` builds its
   response fresh each call. For the full-catalog branch especially, cache it
   until the inner bridge's tool list changes.

5. **Depth-aware subagent UX** — nested agents now filter out cycle/depth-invalid
   specialists, but the UI still doesn't explain why specific models are absent
   from the picker or tool schema.

### Mid-term enhancements

6. **Provider-aware routing budget** — orchestrator could hit rate limits or
   cost ceilings. `ModelConfig.daily_budget_cents` with a running counter in
   `ServeState` would let the router fall back from Claude → GPT-4o → local
   when the budget's exhausted.

7. **Streaming summary for compaction** — `ConversationCompactor` runs the
   summarizer as a one-shot. For long histories this can block the UI for
   seconds. Stream it and show a live "summarizing..." state in the transcript.

8. **Subagent result caching** — if the same subagent config + prompt hits
   twice in a session (common in orchestrator loops), cache the result. Would
   need a good cache-invalidation signal tied to workspace state.

9. **Model-specific tokenizers** — the heuristic `chars / 3.7` is fine for
   budget gating but produces misleading displays. Optional `tiktoken` +
   anthropic's `count_tokens` endpoint would give exact counts for the models
   that matter.

10. **Per-subagent tool profile picker** — right now a subagent's tool profile
    comes from its model config. The orchestrator could specify a narrower
    profile per-spawn (e.g., "use nayru but only with `oos-asm-quality` tools")
    via a `tool_profile` arg on `spawn_subagent`. Already partially supported
    in `SubagentConfig.tool_profile`; needs exposure through the bridge tool
    schema.

### Stretch / research

11. **Subagent transcript export** — save each subagent's full message log
    alongside the session so the user can replay or debug a specific
    delegation after the fact.

12. **Delegation shaping via RL or preference data** — orchestrator logs
    (which specialists got picked for which prompts, and how the result was
    used) could feed back into model training. Existing `export_training`
    could be extended.

13. **Cross-session subagent memory** — let a specialist carry state across
    invocations (e.g., "the last hook you reviewed was door_check.asm").
    Requires careful scoping to avoid context rot; probably a per-model
    append-only log the specialist can query.

14. **Parallel compaction** — run the summarizer concurrently with the first
    tokens of the next response, so compaction doesn't add latency. Risks:
    summary depends on state the response might modify.

15. **Cache warmup command** — `/warmup` sends a minimal prompt with the full
    orchestrator system + tools to create the cache before the user's first
    real turn. Useful for demos and for users who want predictable costs.

### Architectural cleanup

16. **CompositeBridge cloning API** — nested subagents now clone rather than
    mutate shared composites, but the copy/strip logic still lives in
    `SubagentRunner`. A first-class bridge-cloning helper would make that
    behavior reusable and less type-specific.

17. **Single source of truth for "is this model cloud"** — the check appears
    in `ModelConfig.is_cloud`, `is_local`, and ad-hoc in several places.
    Consolidate into a `ProviderKind` enum.

18. **Provider ownership tracking** — `ChatEngine._owns_provider` gets
    muddled when engines are recycled via `get_engine`. Current behavior is
    correct but brittle. A weak registry or explicit owner would help.

19. **Typed IPC protocol** — the serve.py side builds dicts by hand with lots
    of string keys. A shared Pydantic schema or TypedDict would catch drift
    between backend and frontend at change time rather than at runtime.

20. **Test isolation** — `test_frontend_pty.py` is flaky when run alongside
    other tests. Likely a shared PTY or env leak. Quick fix: mark them as
    `@unittest.skipIf(os.environ.get("PYTEST_PARALLEL"), ...)` or split them
    into a separate invocation.

---

## File inventory

### Python (backend)

**New:**
- `src/core/provider.py` — Provider protocol + Local/Anthropic/OpenAI implementations
- `src/core/subagent.py` — runner, config, result, events
- `src/core/subagent_bridge.py` — spawn_subagent/list_subagents tools
- `src/core/compaction.py` — conversation summarizer
- `src/core/deferred_tools.py` — tool_search meta-tool bridge

**Modified:**
- `src/core/engine.py` — Provider-based streaming, compactor integration,
  cache token accumulation, per-round tool fetch, CompactionEvent
- `src/core/config.py` — cloud fields, prompt_cache, context_budget,
  deferred_tools, core_tools, helpers
- `src/app/runtime.py` — ORCHESTRATOR_MODE, build_orchestrator_prompt,
  default_orchestrator_model, resolve_targets extension
- `src/app/serve.py` — ServeState fields, engine factory, subagent runner,
  orchestrator catalog, cache stats, compaction wiring, /subagent,
  /subagent-tools, /orchestrator, /compact
- `src/app/tooling.py` — wrap_bridge_for_model extended layering
- `src/app/backends.py` — minor tweaks
- `pyproject.toml` — `[cloud]` optional dependencies

### Tests (Python)

**New:**
- `tests/test_subagent.py` — runner + bridge (10 tests)
- `tests/test_orchestrator.py` — mode routing (11 tests)
- `tests/test_compaction.py` — compactor (12 tests)
- `tests/test_prompt_cache.py` — cache payload shapes (9 tests)
- `tests/test_deferred_tools.py` — tool_search (15 tests)
- `tests/test_subagent_nested.py` — depth + cycles (5 tests)

### Frontend (TypeScript)

**New:**
- `frontend/src/components/SubagentPanel.tsx`
- `frontend/src/utils/subagentState.ts` + `.test.ts` (14 tests)
- `frontend/src/utils/cacheMetrics.ts` + `.test.ts` (8 tests)

**Modified:**
- `frontend/src/hooks/useBackend.ts` — subagent state, cache tokens,
  lastCompaction, context/compacted handler
- `frontend/src/ipc/protocol.ts` — subagent/* notifications,
  context/compacted, cache token fields, orchestrator_model, provider
- `frontend/src/components/App.tsx` — SubagentPanel wiring, cache props to
  StatusBar
- `frontend/src/components/StatusBar.tsx` — cache badge
- `frontend/src/components/PromptInput.tsx` — orchestrator mode entry
- `frontend/src/theme/index.ts` — orchestrator color

---

## How to use it

### Minimum viable orchestrator setup

```toml
# In chat_registry.toml

[[models]]
name = "claude-sonnet"
model_id = "claude-sonnet-4-20250514"
provider = "anthropic"
tags = ["cloud", "orchestrator"]
max_tokens = 4096
role = "cloud planner"

# Then one or more local specialists, e.g.
[[models]]
name = "nayru"
model_id = "..."
provider = "studio"
tool_profile = "nayru"
context_budget = 8192   # enable auto-compaction
max_tokens = 2048
role = "ASM expert"
```

```bash
export ANTHROPIC_API_KEY=...
z3cli --serve --mode orchestrator --orchestrator claude-sonnet
```

The cloud model receives a catalog of specialists, decides when to delegate,
spawns them in parallel via `spawn_subagent`, and synthesizes results. The
UI shows live specialist activity, caching stats, and any compaction events.

### Useful commands at runtime

- `/mode orchestrator` / `/mode oracle` / `/mode manual`
- `/orchestrator <model>` — set planner (or `auto`)
- `/subagent <model> <prompt>` — manual specialist invocation
- `/subagent-tools on|off` — toggle model-driven delegation
- `/compact [model]` — manual context compaction
- `/tools-write on` — gate write-capable tool calls

---

## Stats

- **Lines of production code added** (approximate): ~3,500
- **Tests added:** 84 across Python and frontend
- **Phases:** 9
- **Provider implementations:** 3
- **New commands:** 4 (`/subagent`, `/subagent-tools`, `/orchestrator`, `/compact`)
- **New IPC notifications:** 8 (7 subagent + 1 compaction)

All phases shipped without breaking existing tests or the legacy single-model
flow. The default configuration (no cloud keys, no orchestrator, no
compaction) behaves identically to pre-phase-1 z3cli.
