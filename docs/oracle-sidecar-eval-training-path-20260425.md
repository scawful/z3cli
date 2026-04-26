# Oracle Sidecar Eval And Training Path

Date: 2026-04-25

## Decision Rule

Do not train `oracle-coder-pro` or `oracle-reasoner-27b` first. Serve the
upstream checkpoints, run zero-shot evals against the existing Oracle packs,
then train only the lane with measured failures worth adapting.

## Phase 0: Data Hygiene

Duplicate-capped derivatives now exist under `/Users/scawful/src/training/datasets`:

- `qwen3_oracle_14b_v7_capped3`
- `oracle_repo_code_v3_capped3`
- `oracle_fast_4b_candidate_v1_capped3`
- `oracle_longctx_v1_capped3`
- `oracle_longctx_dpo_v1_capped3`

The source datasets are untouched. The capped derivatives preserve duplicate
weight metadata and protect exact train/val/test trainable-content overlaps.

Current audit:

- `docs/oracle-training-data-capped3-audit-20260425.md`
- `docs/oracle-training-data-capped3-audit-20260425.json`

## Phase 1: Serve Sidecars

Start only the sidecar being evaluated.

```bash
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 \
  --served-model-name oracle-coder-pro \
  --port 18081 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90
```

```bash
vllm serve Qwen/Qwen3.6-27B-FP8 \
  --served-model-name oracle-reasoner-27b \
  --port 18082 \
  --max-model-len 32768 \
  --reasoning-parser qwen3 \
  --language-model-only \
  --gpu-memory-utilization 0.90
```

## Phase 2: Zero-Shot Coder Eval

Run prompt packs through the OpenAI-compatible endpoint:

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18081/v1 \
  --model oracle-coder-pro \
  --prompt-pack /Users/scawful/src/training/evals/oracle_repo_retrieval_eval_v2.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_repo_retrieval_v2_20260425.jsonl \
  --temperature 0.0 \
  --max-tokens 512
```

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18081/v1 \
  --model oracle-coder-pro \
  --prompt-pack /Users/scawful/src/training/evals/oracle_code_repair_eval_v2.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_code_repair_v2_20260425.jsonl \
  --temperature 0.0 \
  --max-tokens 768
```

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18081/v1 \
  --model oracle-coder-pro \
  --prompt-pack /Users/scawful/src/training/evals/oracle_compile_hard_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_compile_hard_v1_20260425.jsonl \
  --temperature 0.0 \
  --max-tokens 768
```

Score the outputs with existing training scorers:

```bash
python3 /Users/scawful/src/training/scripts/score_oracle_coder_eval.py \
  --answers /Users/scawful/src/training/datasets/sources/oracle_repo_retrieval_eval_answers_v2.jsonl \
  --results /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_repo_retrieval_v2_20260425.jsonl \
  --output /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_repo_retrieval_v2_20260425.summary.json
```

```bash
python3 /Users/scawful/src/training/scripts/score_oracle_coder_eval.py \
  --answers /Users/scawful/src/training/datasets/sources/oracle_code_repair_eval_answers_v2.jsonl \
  --results /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_code_repair_v2_20260425.jsonl \
  --output /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_code_repair_v2_20260425.summary.json
```

```bash
python3 /Users/scawful/src/training/scripts/score_oracle_coder_eval.py \
  --answers /Users/scawful/src/training/datasets/sources/oracle_compile_hard_eval_answers_v1.jsonl \
  --results /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_compile_hard_v1_20260425.jsonl \
  --output /Users/scawful/src/training/evals/runs/oracle_coder_pro_zero_shot_compile_hard_v1_20260425.summary.json
```

Train `oracle-coder-pro` only if the zero-shot run fails in fixable,
Oracle-specific ways: wrong project files, width/ABI drift, unsupported ASAR
syntax, invented labels, or generic Qwen code prose instead of patch output.

## Phase 3: Zero-Shot Reasoner Eval

Use the main Oracle capability pack first because it has an existing scorer.

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18082/v1 \
  --model oracle-reasoner-27b \
  --prompt-pack /Users/scawful/src/training/evals/oracle_main_capability_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_zero_shot_main_capability_v1_20260425.jsonl \
  --temperature 0.6 \
  --top-p 0.95 \
  --max-tokens 1536 \
  --extra-body-json '{"chat_template_kwargs":{"enable_thinking":false}}'
```

```bash
python3 /Users/scawful/src/training/scripts/summarize_oracle_main_capability_eval.py \
  --eval-output /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_zero_shot_main_capability_v1_20260425.jsonl \
  --prompt-pack /Users/scawful/src/training/evals/oracle_main_capability_eval_v1.jsonl \
  --summary-out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_zero_shot_main_capability_v1_20260425.summary.json \
  --details-out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_zero_shot_main_capability_v1_20260425.details.jsonl
```

Then capture long-context behavior for manual review:

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18082/v1 \
  --model oracle-reasoner-27b \
  --prompt-pack /Users/scawful/src/training/evals/oracle_longctx_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_zero_shot_longctx_v1_20260425.jsonl \
  --temperature 0.6 \
  --top-p 0.95 \
  --max-tokens 2048 \
  --extra-body-json '{"chat_template_kwargs":{"enable_thinking":false}}'
```

Train `oracle-reasoner-27b` only if it is strong overall but fails in repeated
Oracle-specific ways. If it merely needs routing or brevity, keep it prompt-only.

## Phase 4: External Deep-Search Sanity Eval

`google/deepsearchqa` is Apache-2.0 and useful as an external agent/retrieval
sanity pack, not as Oracle SFT. It has 900 prompts, answer keys, category
metadata, and no trajectories. Treat it as an eval for planning, search
discipline, and exhaustive final-answer behavior.

Download and convert the CSV into the local training eval shape:

```bash
venv/bin/python scripts/prepare_deepsearchqa_eval.py \
  --download \
  --csv /Users/scawful/src/training/evals/source/google_deepsearchqa/DSQA-full.csv \
  --out /Users/scawful/src/training/evals/google_deepsearchqa_eval_v1.jsonl \
  --answers-out /Users/scawful/src/training/datasets/sources/google_deepsearchqa_eval_answers_v1.jsonl
```

For raw vLLM sidecar endpoints without web/search tools, generate a no-web
sanity variant instead. This does not reproduce the official benchmark; it
checks guessing/refusal behavior.

```bash
venv/bin/python scripts/prepare_deepsearchqa_eval.py \
  --download \
  --agent-mode no-web \
  --csv /Users/scawful/src/training/evals/source/google_deepsearchqa/DSQA-full.csv \
  --out /Users/scawful/src/training/evals/google_deepsearchqa_no_web_eval_v1.jsonl \
  --answers-out /Users/scawful/src/training/datasets/sources/google_deepsearchqa_eval_answers_v1.jsonl
```

Run a small smoke first:

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18082/v1 \
  --model oracle-reasoner-27b \
  --prompt-pack /Users/scawful/src/training/evals/google_deepsearchqa_no_web_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_deepsearchqa_no_web_smoke_20260425.jsonl \
  --limit 50 \
  --temperature 0.0 \
  --max-tokens 768
```

Quick local scoring is available, but it is intentionally rough:

```bash
venv/bin/python scripts/score_deepsearchqa_eval.py \
  --eval-output /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_deepsearchqa_no_web_smoke_20260425.jsonl \
  --answers /Users/scawful/src/training/datasets/sources/google_deepsearchqa_eval_answers_v1.jsonl \
  --summary-out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_deepsearchqa_no_web_smoke_20260425.summary.json \
  --details-out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_deepsearchqa_no_web_smoke_20260425.details.jsonl
```

Use Google's official autorater path for real benchmark claims. The local
scorer is only for triage because DeepSearchQA's official card recommends a
Gemini 2.5 Flash autorater and starter notebook.

## Phase 5: Other Google Eval Packs

The remaining useful Google datasets are staged with one shared converter.
They are eval-only by default and should not be merged into Oracle SFT unless a
fresh eval run exposes a repeated Oracle-relevant failure pattern.

```bash
venv/bin/python scripts/prepare_google_eval_datasets.py \
  --dataset all \
  --download \
  --source-dir /Users/scawful/src/training/evals/source \
  --eval-dir /Users/scawful/src/training/evals \
  --answers-dir /Users/scawful/src/training/datasets/sources
```

Prepared prompt packs:

- `/Users/scawful/src/training/evals/google_facts_grounding_eval_v1.jsonl` - 860 grounded long-context prompts from `google/FACTS-grounding-public`; use manual or official judge review.
- `/Users/scawful/src/training/evals/google_frames_eval_v1.jsonl` - 824 multi-hop RAG prompts from `google/frames-benchmark`; answer companion is `/Users/scawful/src/training/datasets/sources/google_frames_eval_answers_v1.jsonl`.
- `/Users/scawful/src/training/evals/google_ifeval_eval_v1.jsonl` - 541 instruction-following prompts from `google/IFEval`; rule companion is `/Users/scawful/src/training/datasets/sources/google_ifeval_rules_v1.jsonl`.
- `/Users/scawful/src/training/evals/google_simpleqa_verified_eval_v1.jsonl` - 1000 no-tools factuality prompts from `google/simpleqa-verified`; answer companion is `/Users/scawful/src/training/datasets/sources/google_simpleqa_verified_eval_answers_v1.jsonl`.

Recommended smoke order for `oracle-reasoner-27b`:

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18082/v1 \
  --model oracle-reasoner-27b \
  --prompt-pack /Users/scawful/src/training/evals/google_facts_grounding_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_facts_grounding_smoke_20260425.jsonl \
  --limit 25 \
  --temperature 0.0 \
  --max-tokens 1024
```

```bash
venv/bin/python scripts/eval_openai_prompt_pack.py \
  --api-base http://127.0.0.1:18082/v1 \
  --model oracle-reasoner-27b \
  --prompt-pack /Users/scawful/src/training/evals/google_ifeval_eval_v1.jsonl \
  --out /Users/scawful/src/training/evals/runs/oracle_reasoner_27b_ifeval_smoke_20260425.jsonl \
  --limit 50 \
  --temperature 0.0 \
  --max-tokens 1024
```

Use `FRAMES` and `SimpleQA Verified` after those because they need either
official benchmark scoring or a rough answer-containment scorer. `FACTS` and
`IFEval` are better immediate behavior probes for the sidecar.

## Phase 6: External-Answer SFT Smoke

If you explicitly want a training run from the Google material, use the smoke
bundle rather than mixing the eval packs into an existing Oracle dataset.

```bash
python3 /Users/scawful/src/training/scripts/build_oracle_google_external_sft_v1_dataset.py
```

This creates:

- `/Users/scawful/src/training/datasets/oracle_google_external_sft_v1/train.jsonl`
- `/Users/scawful/src/training/datasets/oracle_google_external_sft_v1/val.jsonl`
- `/Users/scawful/src/training/datasets/oracle_google_external_sft_v1/test.jsonl`

The dataset uses only FRAMES and SimpleQA Verified answer companions because
FACTS and IFEval do not contain assistant targets. It intentionally contaminates
those external benchmarks, so do not treat later FRAMES/SimpleQA scores as clean
holdout evidence.

Do not use the Qwen3.5 9B local base for this smoke yet. On 2026-04-25,
`/workspace/training/models/qwen35-oracle-9b-v1/merged` returned all-zero
logits in direct forward checks, and both checkpointed and no-checkpoint
8-step SFT diagnostics kept `grad_norm=0` with zero LoRA `B` updates.

Known-good Qwen3 Oracle 14B diagnostic:

```bash
python3 /Users/scawful/src/training/scripts/windows_zelda_ctl.py launch \
  --task oracle-google-external-qwen3-14b-gradcheck-v1 \
  --config configs/zelda/oracle_google_external_qwen3_14b_gradcheck_v1.toml
```

Active local launch config:

```bash
python3 /Users/scawful/src/training/scripts/windows_zelda_ctl.py launch \
  --task oracle-google-external-qwen3-14b-smoke-v1 \
  --config configs/zelda/oracle_google_external_qwen3_14b_smoke_v1.toml
```

Status:

```bash
python3 /Users/scawful/src/training/scripts/windows_zelda_ctl.py status \
  --task oracle-google-external-qwen3-14b-smoke-v1 \
  --config configs/zelda/oracle_google_external_qwen3_14b_smoke_v1.toml \
  --tail 80
```

2026-04-25 result: the Qwen3 Oracle 14B smoke run completed 120/120 steps in
25m25s, wrote `checkpoint-120` plus `final`, and ended with train loss `1.266`
and last logged loss `1.166508960723877`. Final adapter inspection found 560
adapter tensors; sampled `lora_B` weights were nonzero (`absmax`
`0.0009533412521705031`, `40960` nonzero values), so this was a real gradient
update rather than the Qwen3.5 zero-logit failure mode.

Post-train Oracle capability eval:

- Output: `/Users/scawful/src/training/evals/runs/oracle_google_external_qwen3_14b_smoke_v1_oracle_main_capability_eval_v1.jsonl`
- Summary: `/Users/scawful/src/training/evals/runs/oracle_google_external_qwen3_14b_smoke_v1_oracle_main_capability_eval_v1.summary.json`
- Result: `22/24`, critical `11/12`, mean `0.9757`
- Failures: `oracle_main_v2_capture_assert_jtl`, `oracle_main_v2_torch_loop_return_path`
- Interpretation: this smoke adapter fixed the previous `qwen3-oracle-14b-v7`
  `oracle_main_rep20_hook_contract` miss, but introduced two regressions. Treat
  it as a behavior probe or a source for targeted corrective data, not a
  promotion artifact.
- Regression shape: both misses are short-answer omissions rather than wild
  hallucinations. The capture-assert answer dropped the "upstream bad caller,
  not replacing the runtime guard" clause; the torch-loop answer dropped the
  explicit "`SEP #$30` only on the true exit path" clause.

Targeted follow-up: `qwen3-oracle-14b-v8` was trained as a narrow corrective
from `v7/final`, using only the smoke adapter's useful `rep20` delta plus
preservation anchors for the two smoke regressions.

2026-04-25 result:

- Training completed 50/50 steps in 9m41s.
- Final adapter: `/mnt/d/src/training/output/qwen3-oracle-14b-v8/final`
- Eval output: `/Users/scawful/src/training/evals/runs/qwen3_oracle_14b_v8_oracle_main_capability_eval_v1.jsonl`
- Summary: `/Users/scawful/src/training/evals/runs/qwen3_oracle_14b_v8_oracle_main_capability_eval_v1.summary.json`
- Result: `23/24`, critical `12/12`, mean `0.9861`
- Fixed: `oracle_main_rep20_hook_contract`
- Preserved: `oracle_main_v2_capture_assert_jtl`,
  `oracle_main_v2_torch_loop_return_path`
- Remaining failure: `oracle_main_v2_docs_refuse_fake_symbol`
- Exported Q4_K_M GGUF:
  `/mnt/d/src/training/output/qwen3-oracle-14b-v8/gguf/qwen3-oracle-14b-v8-q4km.gguf`
- Installed LM Studio hardlinks:
  `/mnt/d/models/gguf/lmstudio/qwen3-oracle-14b-v8-q4km.gguf` and
  `/mnt/d/models/gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf`
- z3cli registry-facing id: `gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf`
- Direct `llama-cli` smoke loaded the Q4_K_M artifact and generated
  `V8 ready.`
- Remote LM Studio smoke via `medical-mechanica` loaded the model with
  identifier `gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf`, context `16384`,
  `parallel=1`, `gpu=0.80`, and `ttl=900`. The OpenAI-compatible
  `/v1/chat/completions` endpoint responded from
  `gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf` with `Oracle Pro V8 Online`.
- z3cli also has an SSH fallback node for this exact no-tunnel case:
  `/use home-ssh` selects `oracle-pro-home-ssh`, which calls the Windows LM
  Studio API through SSH and expects the v8 model to already be loaded.
  `/smoke home-ssh` now runs the same route as a built-in probe.

Interpretation: `v8` meets the practical promotion bar and is better than `v7`
on the critical gate. The remaining miss is a scope-control keyword omission,
not a fake-symbol hallucination: it refuses to confirm the symbol and cites the
`$2122`/Time System grounding, but omits the explicit "search the codebase"
next step required by the scorer.

Fresh compile-hard holdout:

- Prompt pack: `/Users/scawful/src/training/evals/oracle_compile_hard_eval_v1.jsonl`
- No-thinking output:
  `/Users/scawful/src/training/evals/runs/qwen3_oracle_14b_v8_oracle_compile_hard_eval_v1_no_think.jsonl`
- No-thinking summary:
  `/Users/scawful/src/training/evals/runs/qwen3_oracle_14b_v8_oracle_compile_hard_eval_v1_no_think.summary.json`
- Result: `4/6`, mean `0.7050`
- Interpretation: `v8` has useful assembler-aware behavior when Qwen3 thinking
  is disabled for code-only evals, but it is not a clean compile-hard coder
  promotion. Keep hard patch synthesis delegated to `oracle-coder` /
  `oracle-coder-pro` until that lane clears the ASAR-heavy gate.

## Promotion Gates

- `oracle-coder-pro` can stay a hidden delegate if it beats or clearly
  complements `oracle-coder` on repo retrieval, code repair, and compile-hard
  scoring.
- `oracle-coder-pro` should be trained if the failures cluster around Oracle
  conventions rather than general code ability.
- `oracle-reasoner-27b` should remain a reasoning sidecar unless it shows
  enough Oracle-specific failures to justify dense 27B adaptation cost.
- `qwen3-oracle-14b-v8` should replace `v7` as the current `oracle-pro`
  candidate if critical Oracle ABI behavior is the primary gate.
- Neither sidecar replaces `oracle-pro` until it passes fresh holdouts that were
  not folded into the capped training derivatives.
