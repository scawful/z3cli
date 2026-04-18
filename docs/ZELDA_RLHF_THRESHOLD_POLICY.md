# Zelda RLHF Threshold Policy (DPO / PPO)

_This is an internal execution playbook for the Zelda shared model stack._

The goal is to stop weak reinforcement-style runs early, keep experiments
repeatable, and only promote `oracle`/`oracle-fast` models when data quality and
coverage are objectively sufficient.

## 1) What this policy covers

- `DPO` on preference pairs from specialist/student disagreement mining.
- `PPO` from rewarded trajectories (not yet in production use, but planned for
  downstream control/optimization experiments).
- Per-profile balance for `domain`, `mode`, and `effort` to avoid one-surface
  overfitting.

## 2) Why thresholding matters

- RL runs can memorize sparse examples and look good early while degrading tool
  discipline.
- Domain/mode imbalance often appears as strong "average" scores and weak
  production behavior (especially in sparse cases like `xref` and OOS debug).
- PPO-style updates are more sample-hungry than DPO and fail noisily when data is
  sparse or reward coverage is poor.

## 3) How these thresholds are chosen

Use a two-stage sizing process so these values stay data-driven:

1. Set minimum split sizes from expected effect size and noise for the target
   metric.
2. Apply profile floors for `pair_source`/`domain`/`mode`/`effort` as anti-bias
   constraints, not average dataset quotas.

For binary quality signals (pass/fail boundaries, safety checks), use:

`n >= z^2 * p * (1 - p) / e^2`

where:

- `z` is confidence z-score (`1.96` for 95% CI),
- `p` is the target passing rate (use `0.5` when unknown for worst case),
- `e` is acceptable absolute error.

Example: with `p=0.5`, `z=1.96`, `e=0.10`, `n ≈ 96`.  
For tighter confidence (±0.07) the same formula gives `n ≈ 196`.

For rollout phases:

- `pilot`: accept higher statistical uncertainty and smaller effect size to quickly
  detect regression risk.
- `production`: tighten size and profile floors to reduce false-confidence in
  sparse surfaces (`xref`, `oos`, `author`).

For PPO-style rewards, the variance is typically higher than DPO pair labels, so
use more samples than pilot DPO first, then widen phase gates in production:

- trajectory distinctness before optimization,
- non-null reward density before weight updates,
- minimum episode/context length to avoid token truncation on repair trajectories.

## 4) DPO minimums for this Zelda use case

Use two gating levels:

- `pilot` (start with bounded runs, keep strict eval visibility)
- `production` (promotion candidate for broader use)

### DPO pilot gate

- `train` pairs: **>= 250**
- `val` pairs: **>= 10**
- `test` pairs: **>= 10**
- Profile coverage (split by pair row):
  - `pair_source`: `nayru >= 60`, `farore >= 40`, `din >= 25`, `majora >= 16`
  - `domain`: `alttp-vanilla >= 120`, `oos >= 70`, `xref >= 16`
  - `mode`: `trace >= 80`, `debug >= 20`, `author >= 20`
  - `effort`: `high >= 120`, `medium >= 80`
- `repair_target_id` uniqueness ratio per train split: **>= 0.20**
- repeats by source `repair_target_id` in train split: max **16x** duplicate
  multiplier
- Missing `_metadata` fields in train rows: **<= 2%**

### DPO production gate

- `train` pairs: **>= 600**
- `val` pairs: **>= 25**
- `test` pairs: **>= 25**
- Profile coverage (split by pair row):
  - `pair_source`: `nayru >= 150`, `farore >= 100`, `din >= 60`, `majora >= 40`
  - `domain`: `alttp-vanilla >= 300`, `oos >= 200`, `xref >= 80`
  - `mode`: `trace >= 220`, `debug >= 80`, `author >= 60`
  - `effort`: `high >= 280`, `medium >= 250`
- `repair_target_id` uniqueness ratio per train split: **>= 0.30**
- `repair_target_id` repeats: max **8x**
- Missing `_metadata` in train rows: **<= 1%**

## 5) PPO thresholds for this use case (planned)

PPO is expected to be much noisier and more brittle at Zelda token scales, so use
harder minimums even in pilot mode:

- `trajectory` rows (distinct `trajectory_id`): **>= 2,000** for pilot,  
  **>= 8,000** for production
- `reward` coverage in pilot data: **>= 90%** non-null
- `reward` coverage in production: **>= 97%** non-null
- Mean episode length in tokens/words: enough room for tool-context; if it cannot
  support the minimum window for repair traces, treat as a build-blocker.
- `reward` model sanity: at least **2 independent eval passes** per
  metric bucket (boundary, tool-chain continuity, correctness).

## 6) Current snapshot: `qwen3_oracle_dpo1_v1`

- Train split: 318 pairs
- Val/Test split: 15/15 pairs
- Pilot DPO gate: **passes**
- Production DPO gate: **fails**
  - Total train size below the 600 minimum
  - `alttp-vanilla` and `oos` are healthy, `xref` and `majora` are still narrow
- Recommendation: keep this as pilot-grade DPO evidence only; add another
  teacher-coverage wave before production promotion.

## 7) Recommended next actions

1. Expand disagreement mining for `majora` and `xref` first; those are the
   thinnest buckets in the current split.
2. Add a preflight validation check to hard-stop launch scripts if pilot/production
   minima are not met.
3. Keep domain/mode/effort min constraints as a first-class routing contract with
   `model_rollouts.toml` and model telemetry reviews.

### Run the preflight locally

```bash
python3 scripts/validate_zelda_dpo_dataset.py \
  /Users/scawful/src/training/datasets/qwen3_oracle_dpo1_v1 \
  --phase pilot
python3 scripts/validate_zelda_dpo_dataset.py \
  /Users/scawful/src/training/datasets/qwen3_oracle_dpo1_v1 \
  --algorithm ppo \
  --phase pilot
```
