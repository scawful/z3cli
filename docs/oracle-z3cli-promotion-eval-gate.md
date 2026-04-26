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
