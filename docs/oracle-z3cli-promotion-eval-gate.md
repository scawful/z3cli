# Oracle z3cli Promotion Eval Gate

Date: 2026-04-26

This gate promotes Oracle-family Zelda models only after they pass real z3cli
tool-use checks. It does not call a plain OpenAI-compatible completion endpoint;
it launches `z3cli --serve`, sends chat turns, observes streamed `tool_call` /
`tool_result` events, and writes JSONL scoring output.

## Files

- Runner: `scripts/run_z3cli_oracle_promotion_eval.py`
- Holdout pack: `/Users/scawful/src/training/evals/oracle_z3cli_promotion_holdout_v1.jsonl`
- Default reports: `reports/oracle-promotion-evals/`

The holdout pack is marked `holdout_do_not_train=true`. Do not mix it into SFT,
DPO, rejection sampling, or distillation data.

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
promotion holdout. For the next promotion slice, create a fresh hard pack with
new rows in these buckets:

1. **Live Mesen2 socket required**: run `windows_oracle_9b_eval.ps1 -RequireMesen`
   and fail fast if no Mesen/Mesen2 process is present.
2. **Exact live-state arguments**: `cpu_state`, `rom_read`, and `disasm_at`
   rows must include requested addresses/counts and must not infer unavailable
   data.
3. **ASAR compile repair**: compile returned snippets or patches with ASAR,
   including stack/width syntax negatives such as unsupported pseudo-ops.
4. **65816 safety traps**: accumulator/index width, bank crossings, DBR/PBR,
   stack balance, and JSR/JSL/RTS/RTL pairing.
5. **Oracle vs vanilla boundary**: require explicit evidence before claiming an
   Oracle of Secrets change differs from vanilla ALTTP behavior.

The seed gate can be promoted to a regression check once the hard gate exists.
A 9B promotion should require both gates to pass, with the 14B `oracle`/
`oracle-pro` lane retained for harder analysis until the hard gate is also
stable.
