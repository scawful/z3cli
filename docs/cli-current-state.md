# z3cli Current State

This document summarizes the current CLI and frontend behavior after the recent
session, UX, shell, and write-review work.

## What Changed

### Session persistence and resume

- Sessions are append-only JSONL files with runtime state updates, not just raw
  model messages.
- Resume restores backend, mode, workspace, ROM, tools on/off, write access,
  verification hooks, broadcast models, focus file, token counts, last-active
  metadata, and sticky permission rules.
- Resume reattaches to the original session file instead of creating a second
  session stream.
- Session lookup prefers exact name matches and handles legacy sessions more
  safely.
- Large `/resume` payloads no longer crash `--serve` because stdout writes retry
  correctly instead of failing on `BlockingIOError`.

### Frontend UX

- The Ink frontend now replaces the visible transcript on resume instead of
  showing only a status line.
- Transcript rendering was changed to avoid welcome-screen/title artifacts on
  first-message transitions and terminal resize.
- `@file` references now support autocomplete against workspace paths and
  basenames.
- Selected files are submitted as structured attachments instead of relying only
  on prompt text rewriting.
- `AttachmentMeta` is now sent with each chat attachment (`path`, `lines`,
  `chars`) and resume logic still supports older path-only entries.
- `#kind:query` references now support active-project autocomplete when a local
  resource-label index is available.
- Selected or inline `#` references are submitted as structured game references
  and restored on resume.
- The prompt supports `Ctrl+P` for the command palette, `Ctrl+A` and other
  cursor/editing shortcuts, and `Ctrl+C` clear-first then exit-on-second-press.
- A context panel surfaces workspace, focus file, attached files, permissions,
  stats, recent sessions, and concurrently loaded models with memory/size data.
- The model picker now shows loaded runtime details and supports unloading a
  selected loaded model.
- Oracle-family chat turns now use hidden prompt-profile routing plus light
  automatic context prefetch in the normal chat flow. When a prompt clearly
  implies Oracle grounding, the backend can preload compact register docs,
  symbol/address lookups, and one nearby disassembly snippet before the model
  answers, without requiring a visible slash-mode switch.

### Permissions, write review, and verification

- Tool permissions support sticky allow/deny rules for the session.
- Write-like tool calls capture a pre-write snapshot, surface a diff review in
  `--serve`, and can be accepted or rejected before the model continues.
- Accepted writes can trigger repo-aware verification commands:
  - `npm run test` and `npm run build` for frontend changes
  - `python3 -m py_compile ...` and unit tests for Python changes
- Verification timeouts now kill the subprocess instead of leaving it running in
  the background.
- Deleted or moved Python files are filtered out before `py_compile`, so valid
  removals no longer produce false failures.
- Multi-file rollback no longer truncates at 12 paths; rejects can restore the
  full tracked change set.

### Shell workflow

- `/shell <command>` runs in a persistent PTY-backed shell session with working
  directory continuity.
- `/shell-log [n]` shows recent shell commands and results.
- `/shell-reset` restarts the shell session.
- The shell follows workspace changes and resume state.

### REPL and serve parity

- The plain REPL now exposes `/verify-hooks`, `/permissions`, `/shell`,
  `/shell-log`, and `/shell-reset`, rather than limiting those features to the
  Ink/`--serve` path.
- The REPL persists and restores verification settings and permission rules.
- The REPL runs post-write verification through engine hooks, but unlike
  `--serve`, it currently auto-accepts write diffs instead of presenting an
  interactive accept/reject dialog.

## Current Command Surface

Core commands:

- `/help`
- `/status`
- `/backend [name]`
- `/backends`
- `/backend-status`
- `/models`
- `/loaded`
- `/servers`
- `/model <name>`
- `/specialist <name>`
- `/mode <name>`
- `/modes`
- `/route <prompt>`
- `/broadcast <a,b,c>`
- `/load [name]`
- `/unload [name|all]`
- `/workspace <path>`
- `/rom <path|none>`
- `/focus <path|clear>`
- `/tools <on|off>`
- `/tools-write <on|off>`
- `/verify-hooks <on|off>`
- `/permissions [clear]`

Model notes:

- `oracle-fast` is now the real pinned local Oracle model: the current 8B
  corrective GGUF.
- `oracle` is the reserved mainline slot. It stays hidden until LM Studio
  reports a runnable local install.
- `/models` and the top-level ready payload keep the primary surface simple:
  `oracle-fast`, `oracle`, plus the active specialist when it differs.
- The wider local bench stays available through the model manager catalog tabs:
  `qwen3-oracle-8b`, `nayru`, `farore`, `majora`, `hylia`, and related quants.
- `oracle-pro` now points at the gate-cleared local `14B Oracle-Pro · q4km`
  artifact.
- `oracle-mythic` is the manual-only heavy-model alias for the older 27B
  switchhook lane.
- `oracle-coder` remains internal and spawn-only. It should appear only in
  delegation surfaces or bench/internal catalog views, not as part of the main
  Oracle surface.
- The intended local host is now `medical-mechanica` WSL2 + RTX `5090`; Mac is
  the control plane/fallback machine, and Vast is the fallback when the shared
  desktop cannot spare the GPU.
- The preferred studio control path for that host is now `afs-hostd`: set
  `AFS_HOSTD_URL=http://127.0.0.1:8766` plus `LMSTUDIO_BASE_URL` pointing at a
  local tunnel (for example `http://127.0.0.1:2234/v1`) so `/load`, `/unload`,
  `/loaded`, and backend-status checks go through the Windows host API.
- The same host daemon now exposes WSL runtime status and start/stop control
  for training and `vllm`, so the Windows-side training controller can use the
  same local tunnel instead of a second SSH + PowerShell control path.
- The older `Z3CLI_LMSTUDIO_REMOTE_HOST=medical-mechanica` path still exists as
  a fallback when the daemon is not running, but it is no longer the preferred
  control-plane shape.
- Legacy `switchhook*` names resolve through `oracle-mythic`; legacy
  `oracle-main*` names now resolve through `oracle-fast`.
- `/shell [command]`
- `/shell-log [n]`
- `/shell-reset`
- `/reset [model|all]`
- `/stats`
- `/save`
- `/sessions`
- `/resume <name>`
- `/compact`
- `/export-training [out]`
- `/exit`

Prompt features:

- `@path` attaches workspace files to the turn
- `#kind:query` attaches active-project game metadata to the turn
- `AttachmentMeta` includes file `lines` and `chars` to preserve context stats
  for future tooling without requiring file rereads.
- structured construct refs preserve canonical ids / labels for room, sprite,
  overworld map, item, entrance, music, and message references where available
- Backward compatibility: legacy `path`-only attachments load from old sessions
  with `lines` and `chars` defaulting to `0`.
- command palette via `Ctrl+P`
- clear prompt on first `Ctrl+C`, exit on second `Ctrl+C`

## Validation Added

Backend coverage now includes tests for:

- session resume fidelity
- attachment resolution
- shell-session persistence
- write-review restore behavior
- verification command selection
- verification timeout cleanup
- REPL command parity for shell, permissions, and verify-hooks

Frontend coverage now includes tests for:

- `@file` picker flows
- structured attachment submission
- command palette open/submit
- prompt editing shortcuts
- `Ctrl+C` clear/exit behavior
- context-panel resize logic
- transcript grouping helpers

## Known Gaps

- The interactive write accept/reject dialog still only exists in `--serve`.
- There are no full terminal end-to-end tests for raw Ink repaint behavior
  beyond the current PTY smoke coverage.
- Structured attachments currently focus on whole-file context; there is not yet
  first-class range or diff attachment support.

## Observed Session Failures (2026-04-17)

The following issues were reproduced from saved sessions under
`~/.local/share/z3cli/sessions/` and reflect real user-visible behavior, not
just code inspection.

### `2026-04-17_081707_322382_hello.jsonl` (`din`)

- `din` emitted `0` real tool invocations for the full session.
- It repeatedly described `profile_routine` instead of calling it.
- It also produced pseudo-tool JSON in assistant text, for example:
  - `{"name": "profile_routine", "arguments": {"address": "$068328"}}`
- Failure mode: tool-available model, but prose-first behavior plus fake tool
  syntax.

### `2026-04-17_083232_183437_hello.jsonl` (`farore`)

- `farore` emitted `3` real tool calls: `inspect_room`, `list_sprites`,
  `read_state`.
- The first two calls were denied during the original run because the approval
  path was effectively timing out too aggressively for the interactive UI.
- `read_state` then failed because no live Mesen2 socket was available.
- Multiple assistant messages leaked hidden chain-of-thought style text directly
  into user-visible output, for example:
  - `The user is greeting me...`
  - `The user denied the tool calls...`
- The same session also showed identity drift into false Anthropic/Claude
  claims, including statements such as:
  - `I'm an AI assistant developed by Anthropic`
- Failure mode: better tool instinct than `din`, but approval flow, emulator
  bootstrap, reasoning leakage, and provenance drift were all visible.

### `2026-04-17_084410_739565_hello.jsonl` (`majora`, then `qwen3-oracle-8b`)

- `0` real tool invocations were logged even when the user asked for codebase
  analysis and explicitly called out hallucinations.
- The model answered with fabricated subsystem details instead of inspecting the
  workspace.
- It later degraded into low-quality text responses such as:
  - `I will use AFS to examine the compressed graphics file at $018000.`
  - `I have read the code.`
- The final state counters reported `tool_call_count = 3` even though the saved
  session contains no `tool_invocation` records, which suggests a metrics/state
  accounting mismatch worth auditing.
- Failure mode: severe tool avoidance plus possible stats inconsistency.

### `2026-04-17_085030_819313_hello.jsonl` (`hylia`)

- `hylia` is the current positive control.
- It emitted `2` real tool calls: `lookup_reference` and `search_history`.
- It did not show Anthropic identity drift.
- It still leaked hidden reasoning-style preambles in multiple replies.
- Failure mode: tool usage is materially better here, but hidden reasoning is
  still reaching the transcript.

### `2026-04-17_090311_222416_read-a-real-source.jsonl` (`din`, one-shot `--prompt`)

- This run was executed after fixing one-shot prompt mode so it now creates a
  session artifact.
- `din` emitted real tool calls this time: `3` invocations of `read_context`.
- The tool choice was still poor for the active workspace:
  - `read_context` is currently backed by AFS `context.read`
  - the configured AFS roots only include `/Users/scawful/src/lab`
  - the active Oracle workspace lives under `/Users/scawful/src/hobby`
- Result: even correct-looking Oracle paths failed with
  `Path outside allowed roots`.
- Failure mode: Din now calls tools under stronger prompting, but its first-line
  file-reading tool is mismatched to non-`lab` workspaces.

### `2026-04-17_091526_187805_read-a-real-source.jsonl` (`din`, after workspace-reader + MCP shutdown fixes)

- `din` emitted a real `read_context` call for `Oracle_main.asm`.
- The file read succeeded against the active Oracle workspace and returned the
  file contents through the local workspace reader.
- The one-shot CLI run exited cleanly afterward; the previous MCP
  `cancel scope` shutdown crash did not recur.
- Remaining failure mode: response quality is still poor after the successful
  tool call. Din over-narrated its process and then produced a weak syntax
  critique (`incsrc` spacing) instead of a grounded code issue.

### `2026-04-17_140938_522669_use-tools-to-read.jsonl` (`qwen3-oracle-8b`, one-shot prompt smoke)

- This smoke was run against the already-loaded LM Studio model
  `gguf/zelda/qwen3-oracle-8b-v1-corrective2-q8_0.gguf`.
- The session file contains only the user message and no assistant/tool events.
- The live process printed repeated `ListToolsRequest` activity and an AFS stale
  index warning, then stalled indefinitely until the CLI process was killed.
- Failure mode: one-shot prompt mode can still hang before first model output on
  a tool-enabled local Qwen3 model, likely during early tool discovery or bridge
  setup rather than during generation itself.

### `2026-04-17_143036_328726_reply-with-the-single.jsonl` (`qwen3-oracle-8b`, tools enabled after native-tool fallback fix)

- This is the same local Qwen3 model after disabling native LM Studio tool
  schemas for the affected Qwen3 entries and routing them through the
  engine's manual/XML tool loop instead.
- The one-shot prompt returned promptly with tools still enabled:
  - `READY`
- Failure mode from `2026-04-17_140938_522669...` no longer reproduced.

### `2026-04-17_143253_919827_use-tools-to-read.jsonl` (`qwen3-oracle-8b`, tool-required one-shot after XML/manual fallback fix)

- The one-shot tool-required prompt no longer stalled.
- The model first emitted a bad guessed tool name (`tool_read`), received a tool
  error, then recovered via `tool_search` using the shorthand form
  `tool_search{"query":"tool_read"}`.
- The engine now accepts that shorthand manual-tool syntax and continued the
  loop instead of dead-ending on plain text.
- The run finished with:
  - `The first non-comment line of Oracle_main.asm is org $008000.`
- Residual risk: the final answer was not grounded in a successful file-read
  tool result. The transport/tool loop is now healthy enough to continue, but
  first-tool choice and post-error recovery quality still need prompt/model
  tuning.

### One-shot CLI teardown bug

- The same single-shot `--prompt` smoke run also crashed during shutdown with:
  - `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in`
- The traceback originated during MCP bridge teardown in `MCPBridge.close()`
  via `stdio_client` / `anyio` task-group cleanup.
- Failure mode: one-shot prompt execution is now inspectable, but teardown is
  still unstable after tool-backed runs.

### `2026-04-17_145723_092415.jsonl` (`qwen3-oracle-8b`, live `/subagent` smoke before subagent tool-path fix)

- This was the first live `z3ui` spot-check for subagent-labeled permission
  reasons using the already-loaded `qwen3-oracle-8b` model.
- The session recorded only:
  - `subagent/start`
- No `subagent/text`, `subagent/tool_call`, or `tool/permission_request`
  events followed.
- Failure mode: delegated local Qwen3 runs were still using the older
  subagent tool path, which did not honor the `native_tools = false` fallback
  or the model's deferred-tool wrapping. Child runs could stall immediately
  after spawn even though the top-level model path had already been fixed.

### Direct serve-mode subagent spot-check (`qwen3-oracle-8b`, after subagent tool-path fix)

- After updating `SubagentRunner`, the same delegated prompt progressed
  normally through the manual/XML loop:
  - `subagent/start`
  - `subagent/text` streaming the `<tool_call>...tool_search...</tool_call>`
    block
  - `subagent/tool_call` for `tool_search`
  - `tool/permission_request` with:
    - `reason: "subagent [qwen3-oracle-8b]"`
- A scripted allow-once decision for `tool_search` then produced:
  - `subagent/tool_result` revealing `fs.write`
  - `subagent/tool_call` for `fs.write`
  - `tool/permission_request` with:
    - `reason: "subagent [qwen3-oracle-8b] · write tool: will modify subagent_permission_probe.txt"`
- A deny-once decision for the write produced the expected:
  - `subagent/tool_result` → `[Tool call denied by user]`
  - `subagent/done`
- This closes the backend half of the UI spot-check: the serve stream now
  carries the exact subagent-attributed reason string that `PermissionDialog`
  already renders as `why -> ...`.

## UX Issues Seen In Sessions

- Unsupported markdown fence labels such as `asm` produced repeated terminal
  warnings:
  - `Could not find the language 'asm'...`
- Live markdown rendering during token streaming caused visible flicker.
- Transcript history felt inaccessible because terminal scrollback was not
  sufficient on its own.
- Tool turns used too much vertical space because of nested borders and repeated
  status text.

## Fixes Landed In Current Tree

- Unsupported fence labels are now sanitized before terminal markdown rendering,
  which suppresses the `asm` warning spam.
- Streaming messages now render as plain text until the final transcript entry,
  which removes the markdown flicker path.
- Transcript navigation now supports in-app scrolling shortcuts such as
  `PgUp`/`PgDn`.
- Tool and message rendering were compacted to reduce border nesting and wasted
  vertical space.
- The engine no longer applies a hard `2s` default timeout around the permission
  hook, so interactive tool approvals can complete normally.
- Raw Mesen2-backed tools now attempt socket refresh and launcher bootstrap
  before failing immediately on missing socket state.
- Local Qwen/LM Studio models now receive explicit identity guidance telling them
  not to claim Anthropic/Claude/OpenAI provenance.
- Tool-enabled models now receive stronger tool-first prompting, with extra bias
  for requests that obviously require inspection.
- One-shot REPL prompt mode now starts and closes a session file, so serial
  smoke prompts leave artifacts under `~/.local/share/z3cli/sessions/`.
- `read_context` for specialist adapters now uses a local workspace-rooted file
  reader instead of relying on AFS `context.read` policy for basic source
  inspection.
- MCP stdio sessions now live inside dedicated per-server worker tasks, so
  connect and shutdown happen in the same task and avoid the previous anyio
  cancel-scope crash on one-shot exit.
- `--serve` now strips common hidden-reasoning/planning paragraphs from
  assistant-visible text before it is persisted or surfaced in final assistant
  transcript messages.
- Tool-backed assistant replies now get an automatic `Evidence: <tool> -> ...`
  anchor when the model tries to summarize a tool result without clearly citing
  it.
- Repeated startup collision warnings from overlapping `yaze-editor` / `z3ed`
  ROM tools are compacted into a short summary instead of dumping every raw
  collision line into the top of the session.
- Local Qwen3 models can now opt out of LM Studio native tool schemas and use
  the engine's manual/XML tool loop instead, which fixes the one-shot
  tool-enabled prompt stall seen on `qwen3-oracle-8b`.
- The engine now recognizes bare shorthand manual tool calls such as
  `tool_search{"query":"..."}` when a local model emits them as the full
  assistant turn.
- Delegated/subagent runs now mirror the top-level local-model path:
  model-aware bridge wrapping always runs, deferred tools are preserved, local
  identity/tool prompts are injected, and `native_tools = false` correctly
  routes child Qwen3 models through the manual/XML tool loop instead of LM
  Studio native tool schemas.

## Remaining Open Problems

- Prompting is improved, but not yet strong enough to guarantee tool-first
  behavior on weaker local models such as `din` and `majora`.
- Local-model post-tool reasoning quality still needs work; Din in particular
  can now inspect real files but still draws weak or incorrect conclusions from
  the returned context.
- Session stats may be overstating tool activity in some resumed or switched
  sessions; `tool_call_count` needs verification against the event log.
- The new assistant-output sanitizer is conservative and paragraph-based. It
  suppresses obvious leaked planning text, but it is not yet a full semantic
  filter for every form of reasoning leakage.
- Some local Qwen3 models still choose poor first tool names in the manual/XML
  tool mode and may recover imperfectly after tool errors even though the stall
  itself is fixed.
- Manual smoke tests against LM Studio models should stay serial to avoid
  loading multiple large models at once during debugging.
