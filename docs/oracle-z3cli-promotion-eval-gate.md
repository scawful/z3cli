# Oracle z3cli Promotion Eval Gate

Date: 2026-04-26

This gate promotes Oracle-family Zelda models only after they pass real z3cli
tool-use checks. It does not call a plain OpenAI-compatible completion endpoint;
it launches `z3cli --serve`, sends chat turns, observes streamed `tool_call` /
`tool_result` events, and writes JSONL scoring output.

## Files

- Runner: `scripts/run_z3cli_oracle_promotion_eval.py`
- Holdout pack: `/Users/scawful/src/training/evals/oracle_z3cli_promotion_holdout_v1.jsonl`
- Hard holdout pack: `evals/oracle_z3cli_hard_holdout_v1.jsonl`
- Default reports: `reports/oracle-promotion-evals/`

The holdout packs are marked `holdout_do_not_train=true`. Do not mix them into
SFT, DPO, rejection sampling, or distillation data.

## Live Gate

Run this after the candidate model is installed in the local model catalog:

```bash
python3 scripts/run_z3cli_oracle_promotion_eval.py \
  --prompt-pack /Users/scawful/src/training/evals/oracle_z3cli_promotion_holdout_v1.jsonl \
  --model oracle-qwen35-9b \
  --workspace /Users/scawful/src/hobby/z3cli \
  --out reports/oracle-promotion-evals/oracle_qwen35_9b_promotion.jsonl
```

The command exits `0` only when every row passes. It exits nonzero if a row
misses the required tool, calls the wrong tool, omits required arguments,
exceeds the tool-call budget, or emits a forbidden final-answer pattern.

By default the runner does not auto-start LM Studio. Add
`--auto-start-server` only when that is intentional for the current machine.

### Windows candidate-gate command

For the Windows 5090 host, use the wrapper script so LM Studio startup,
`oracle-9b-router` loading, hostd fallback, and serve-readiness settings stay
consistent:

```powershell
Set-Location D:\src\hobby\z3cli
.\scripts\windows_oracle_9b_eval.ps1 `
  -PromptPack D:\src\training\evals\oracle_z3cli_promotion_holdout_v1.jsonl `
  -Out reports\oracle-promotion-evals\oracle_9b_router_full_windows_manual_z3cli_workspace_YYYYMMDD.jsonl
```

The wrapper sets:

- `Z3CLI_ZELDA_WORKSPACE=D:\src\hobby\oracle-of-secrets`
- `LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1`
- `Z3CLI_LMSTUDIO_HOSTD_URL=http://127.0.0.1:1` to force direct LM Studio API
  fallback when `afs-hostd` is not running
- `Z3CLI_SKIP_MODEL_MEMORY_ESTIMATES=1` so `z3cli --serve` readiness does not
  hang on model-memory estimation

Use `-RequireMesen` only for a live-emulator gate. Without it, Mesen rows should
only assert graceful unavailable behavior when the Mesen2 socket/process is not
running. Use `-SkipLoad` or `-SkipServerStart` when LM Studio is already in the
exact desired state. The wrapper refuses to overwrite an existing output path
unless `-ForceOverwrite` is passed.

The wrapper also discovers the local Windows ASAR executable and exports
`Z3CLI_ASAR_PATH`. Override it with `-AsarPath` if the default `D:\src`
locations move.

Use `--mode manual` for candidate-specific gates. `--mode oracle` routes the
chat target through the canonical `oracle` slot and can test the wrong model.
Use `--workspace D:\src\hobby\z3cli` for this holdout pack because several rows
inspect z3cli docs/config. Keep `Z3CLI_ZELDA_WORKSPACE` set to
`D:\src\hobby\oracle-of-secrets` so symbol/ROM/emulator tools still resolve the
Zelda project.

## Scoring An Existing Session

When a z3cli session has already captured the eval turns, score it directly:

```bash
python3 scripts/run_z3cli_oracle_promotion_eval.py \
  --prompt-pack /Users/scawful/src/training/evals/oracle_z3cli_promotion_holdout_v1.jsonl \
  --session ~/.local/share/z3cli/sessions/<session>.jsonl \
  --model oracle-qwen35-9b \
  --model-filter \
  --out reports/oracle-promotion-evals/oracle_qwen35_9b_session_score.jsonl
```

Session scoring ignores `oracle-prefetch-*` tool records by default so runtime
prefetch cannot mask a missing model-emitted tool call. Use
`--include-prefetch` only for a separate runtime-prefetch check, not for model
promotion.

## Current Scope

The first holdout seed covers the current compact Oracle adapter surface:

- `workspace_read`
- `cpu_state`
- `rom_read`
- `disasm_at`
- `label_lookup`
- `grep_disasm`

This is a seed gate, not the final promotion suite. Expand it with more fresh,
untrained rows before promoting `oracle-qwen35-9b` to the plain `oracle` slot.

## Latest Windows Result

Date: 2026-05-02 local / 2026-05-03 UTC.

- Host: `medical-mechanica`.
- Model: `oracle-9b-router` loaded as
  `gguf/zelda/oracle-9b-candidate-v5-q4km.gguf`.
- Full gate output:
  `reports/oracle-promotion-evals/oracle_9b_router_full_windows_manual_z3cli_workspace_no_prefetch_parsefix_hostdfix_skipmem_argrepair_fallback_20260502.jsonl`.
- Session artifact:
  `reports/oracle-promotion-evals/oracle_9b_router_full_windows_manual_z3cli_workspace_no_prefetch_parsefix_hostdfix_skipmem_argrepair_fallback_20260502_artifacts/sessions/2026-05-03_002829_745182.jsonl`.
- Full gate: 12/12 rows passed (`pass_rate=1.0`).
- Targeted previously-failing rows also passed after runtime hardening: 3/3.
- Wrapper verification after adding partial-argument repair:
  `reports/oracle-promotion-evals/oracle_9b_router_wrapper_verify_20260502_002.jsonl`
  also passed 12/12. Its session artifact is
  `reports/oracle-promotion-evals/oracle_9b_router_wrapper_verify_20260502_002_artifacts/sessions/2026-05-03_005956_666648.jsonl`.

This is a green seed-gate result for the compact z3cli Oracle adapter. It is not
sufficient by itself to promote the 9B to the plain `oracle` slot: the next gate
must exercise live Mesen2 state, real ROM/disassembly reads, ASAR compile/repair
cases, negative no-hallucination cases, and 65816 width/bank/JSR/JSL traps.

## Next Hard Gate

Do not train on `oracle_z3cli_promotion_holdout_v1`; keep it as the seed
promotion holdout. The fresh hard pack is now committed at
`evals/oracle_z3cli_hard_holdout_v1.jsonl` and mirrored for the shared training
workspace at `/Users/scawful/src/training/evals/oracle_z3cli_hard_holdout_v1.jsonl`.
Run it on Windows with:

```powershell
Set-Location D:\src\hobby\z3cli
.\scripts\windows_oracle_9b_eval.ps1 `
  -PromptPack D:\src\hobby\z3cli\evals\oracle_z3cli_hard_holdout_v1.jsonl `
  -Out reports\oracle-promotion-evals\oracle_9b_router_hard_windows_YYYYMMDD.jsonl `
  -RequireMesen
```

This hard pack covers:

1. **Live Mesen2 socket required**: run `windows_oracle_9b_eval.ps1 -RequireMesen`
   and fail fast if no Mesen/Mesen2 process is present.
2. **Exact live-state arguments**: `cpu_state`, `rom_read`, and `disasm_at`
   rows must include requested addresses/counts and must not infer unavailable
   data.
3. **ASAR compile repair**: compile returned snippets or patches with ASAR,
   including stack/width syntax negatives such as unsupported long `STZ`.
4. **65816 safety traps**: accumulator/index width, bank crossings, DBR/PBR,
   stack balance, and JSR/JSL/RTS/RTL pairing.
5. **Oracle vs vanilla boundary**: require explicit evidence before claiming an
   Oracle of Secrets change differs from vanilla ALTTP behavior.

The seed gate can be promoted to a regression check once the hard gate exists.
A 9B promotion should require both gates to pass, with the 14B `oracle`/
`oracle-pro` lane retained for harder analysis until the hard gate is also
stable.

## First Hard-Gate Results (2026-07-04, no Mesen)

Both runs on `medical-mechanica` via `windows_oracle_9b_eval.ps1`, without
`-RequireMesen` (no Mesen2 process; emulator rows degraded to
graceful-unavailable mode):

- `oracle-9b-router` (v5 + guard prompts): **1/8**
  (`reports/oracle-promotion-evals/oracle_9b_router_hard_windows_20260704.jsonl`)
- `oracle` (qwen3-oracle-14b-v8): **1/8**
  (`reports/oracle-promotion-evals/oracle_14b_v8_hard_windows_20260704.jsonl`)

Only `ozh_live_rom_read_exact_hook_01` passed for either model. Three separable
causes, confirmed from `observed.final_text` and tool results:

1. **Missing Mesen2** (environmental): `cpu_state` and `disasm_at` return
   "unavailable without a live Mesen2 disassembler", so
   `ozh_live_cpu_state_pc_flags_01`, `ozh_live_disasm_jsr_contract_01`, and
   `ozh_hook_displaced_logic_evidence_01` cannot produce the required
   tool-result evidence in this mode. Re-run with `-RequireMesen` once Mesen2
   is up.
2. **v5-only empty/truncated finals**: v5's final answers cut mid-sentence at
   ~100-300 chars ("…Based on those bytes I should") or are fully empty; the
   14B's finals end cleanly. This is the known v5 q4km thinking-template
   budget-burn. Fix direction: no-think template variant of the v5 GGUF or a
   larger/finalized post-tool completion budget in the serve path.
3. **Shared real gaps**: neither model produced a compilable ASAR patch on
   `ozh_asar_clear_long_wram_01` / `ozh_asar_jsr_rts_contract_01` (missing
   `ClearOracleScratch`/`$7E0200`/`RTL`; `compile_final_asar` had no assembler
   source; the 14B skipped tools entirely and answered in one line), and both
   called only one of the two required tools on
   `ozh_oracle_vanilla_boundary_songbank_01`. The tool-first system prompts
   may be steering models away from emitting ASM on compile rows — worth a
   prompt-calibration pass before blaming weights.

Note on the `oracle-9b-router` lane: `src/core/oracle_teacher_router.py` is a
guard-prompt shim, not a two-model proxy. The matched guards (songbank, hook
stub, displaced) did not rescue v5 on these rows. afs-scawful's
`oracle-teacher` chat-harness router (2026-07-03) does real two-model
escalation; wiring that into the z3cli serve path is the escalation experiment
this result motivates, but the identical 14B score above says escalation alone
will not clear the hard gate without fixes to causes 1 and 3.

## Runtime Fixes (2026-07-04, same day)

Cause 2 (v5 empty finals) was root-caused and fixed without touching weights:

1. **No-think GGUF variant.** Direct LM Studio probes showed v5 emitting its
   whole answer inside `reasoning_content` and stopping with zero visible
   content (`finish_reason=stop`, 77/78 tokens reasoning). Qwen3.5 ignores
   `/no_think`. Applied the scawfulbot recipe: flipped the chat template's
   `enable_thinking` default (generation prompt now pre-closes
   `<think>\n\n</think>\n\n`) via `gguf.scripts.gguf_new_metadata` — a
   metadata-only rewrite. New artifact:
   `gguf/zelda/oracle-9b-candidate-v5-nothink-q4km.gguf` (both LM Studio
   hosts' registries and this wrapper's default `-ModelPath` now point at it;
   the thinking original is preserved).
2. **Answer-round prose retry** (`src/core/engine.py`). Wire captures
   (`lms log stream`) showed the model answering *in prose* after tool
   results, but on harder rows it emits another `<tool_call>` in the
   tools-disabled answer round; the engine dropped it and ended with an empty
   final. The engine now retries that round once with an explicit
   prose-only instruction (`_ANSWER_ROUND_PROSE_RETRY_PROMPT`) before falling
   back. Test: `test_answer_round_tool_call_only_output_retries_once_with_prose_instruction`.

Results with both fixes (no Mesen, `oracle-9b-router` = nothink v5):

- Seed gate: 12/12, 11/12, 10/12 across three runs — the gate is noisy at
  `temperature=0.15`; failures are now content/arg slop (e.g. `<invalid>`
  passed as a disasm address, wrong row answered), never the silent
  empty-final disease alone. Consider greedy decoding for promotion runs.
- Hard gate: still 1/8. The remaining hard failures are (a) Mesen-live
  evidence rows and (b) the model persistently tool-calling instead of
  answering on content it cannot handle — it defies the prose retry too.
  That is the model-capability lane (session-replay preference data per
  `~/src/training` docs), not a runtime bug.
