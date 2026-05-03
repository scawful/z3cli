# Zelda Model Work Handoff

Date: 2026-04-25
Owner: scawful
Scope: z3cli / Oracle-series Zelda hacking models

## Summary

The Zelda side of the current model work is the Oracle-series z3cli lane, not
the scawfulbot avatar/persona lane. Keep those datasets, registry names,
prompts, evals, and deployment decisions separate.

The active Zelda run is the Qwen3.5 9B Oracle candidate, launched under the
legacy remote directory name `farore_qwen35_9b`. It should be treated as the
first serious `oracle-qwen35-9b` candidate for z3cli, with Farore-style
debug/FIM behavior and the normal Oracle tool-first adapter profile.

## Current Live Run

Last checked: 2026-04-25 21:54 EDT.

| Field | Value |
| --- | --- |
| Label | `farore-qwen35-v1` |
| z3cli target alias | `oracle-qwen35-9b` |
| Family | `oracle` |
| Base | `Qwen/Qwen3.5-9B` |
| Phase | SFT |
| Remote | `ssh3.vast.ai:16648` |
| Remote root | `/root/farore_qwen35_9b` |
| Train command | `python training/train_unsloth.py --preset qwen3.5-9b --data-dir data/output/farore_qwen35_sft --output-dir training/output_farore_qwen35_sft --epochs 1 --batch-size 1 --grad-accum 8 --save-merged` |
| Latest observed progress | `2589/2655`, about 98 percent |
| Latest checkpoint | `training/output_farore_qwen35_sft/checkpoint-2500` |
| SFT merged artifact | not present yet |
| DPO artifact | not present yet |
| Error state | no traceback, CUDA OOM, or trainer crash observed in tail |

The long eval at step `2500` completed and checkpoint `2500` was written. The
run resumed normal training afterward and was still active at the latest check.
Expect the next major state transition to be final SFT save/merge.

## Monitoring Commands

Use direct SSH/log checks as the source of truth while the training dashboard
parser is still being hardened.

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 -p 16648 root@ssh3.vast.ai \
  'cd /root/farore_qwen35_9b &&
   pgrep -af "train_unsloth|python" || true &&
   ls -dt training/output_farore_qwen35_sft/checkpoint-* 2>/dev/null | head -5 &&
   test -d training/output_farore_qwen35_sft/merged && echo merged-ready || echo merged-missing &&
   tail -c 18000 training_sft.log | tr "\r" "\n" |
     grep -E "[0-9]+%.*[0-9]+/[0-9]+|train_loss|eval_loss|Traceback|RuntimeError|CUDA|error|Saving|merged|checkpoint|Restored" |
     tail -n 35'
```

The local exporter can still be useful for z3ui state, but do not treat it as
authoritative until its SSH timeout and nested eval-loop parsing are fixed:

```bash
python3 /Users/scawful/src/lab/scawfulbot/scripts/export_training_state.py \
  --config /Users/scawful/src/lab/scawfulbot/config/active_runs.json
```

## Model Landscape After Farore Lands

Keep the public surface simple:

| Public slot | Role | Current interpretation |
| --- | --- | --- |
| `oracle-fast` | fast local Zelda assistant | current small corrective Oracle floor |
| `oracle` | daily Zelda hacking model | promote `oracle-qwen35-9b` only after evals clear |
| `oracle-pro` | harder analysis and patch planning | current 14B Oracle-Pro lane |
| `oracle-mythic` | manual heavy-model lane | 27B research/opt-in path |

Keep the specialist bench available internally:

| Specialist | Use |
| --- | --- |
| `nayru` | explanation, teaching, hardware docs |
| `din` | optimization, hook contracts, patch hygiene |
| `navi` | FIM/autocomplete, quick debug triage, z3cli workflow repair |

`veran`, `hylia`, and `majora` are retired from the active z3cli catalog and
runtime adapter registry. The old adapter code can stay as historical reference
code, but the picker/catalog surface should consolidate around `din`, `nayru`,
and `navi`.
The former `farore` autocomplete model now resolves as a legacy alias for
`navi`; keep the Farore-labeled training run on `oracle-qwen35-9b`.

The new Qwen3.5 9B run should not immediately replace every Farore/Nayru-style
entry. First register it as `oracle-qwen35-9b`, then promote it to the plain
`oracle` slot only if it beats the existing floor on grounded evals.

## z3cli Registry State

The z3cli registry already has the intended candidate entry:

- `config/chat_registry.toml`
- model name: `oracle-qwen35-9b`
- model id: `gguf/zelda/oracle-qwen35-9b-v1-q4km.gguf`
- tool profile: `oracle`
- prompt: `config/prompts/oracle_qwen35_9b.md`
- aliases include `oracle-qwen35-9b-v1`, `qwen35-oracle-9b`, and
  `qwen35-oracle-9b-v1`

After conversion/import, verify that LM Studio reports the installed model id
that matches the registry:

```bash
python3 -m z3cli models catalog
python3 -m z3cli route list advanced
python3 -m z3cli route smoke oracle-qwen35-9b
```

If the model id changes during conversion, update the registry before trying to
route through z3ui.

## Landing Checklist

When the SFT run finishes:

1. Confirm the merged Hugging Face artifact exists:

   ```bash
   ssh -p 16648 root@ssh3.vast.ai \
     'test -d /root/farore_qwen35_9b/training/output_farore_qwen35_sft/merged && echo ready'
   ```

2. Pull or sync the merged artifact to the local model staging area.

3. Run a small eval before quantization if practical:

   - `oracle_main_capability_eval_v1.jsonl`
   - `oracle_repo_retrieval_eval_v2.jsonl`
   - `oracle_code_repair_eval_v2.jsonl`
   - `oracle_compile_hard_eval_v1.jsonl`

4. Convert to the first serving quant:

   ```bash
   model-mgr convert oracle-qwen35-9b-v1 --quantize q4km
   ```

5. Import/register the GGUF with LM Studio under:

   ```text
   gguf/zelda/oracle-qwen35-9b-v1-q4km.gguf
   ```

6. Smoke the route through z3cli:

   ```bash
   python3 -m z3cli route smoke oracle-qwen35-9b
   ```

7. Run a short tool-grounding prompt in normal chat mode before using it for
   write-like work:

   ```text
   What does $420B do, and how would you verify a DMA setup in this project?
   ```

8. Only after eval review, decide whether to run DPO. Do not start DPO just
   because SFT finished.

## Eval Gates

Promote the candidate only if it improves or holds steady in the failure modes
that matter for Zelda hacking:

- does not invent labels, ROM addresses, tool names, or register state
- separates vanilla ALTTP behavior from Oracle of Secrets project changes
- uses tool evidence before proposing bug fixes
- writes ASAR-compatible 65816 when code is requested
- respects accumulator/index width, bank boundaries, stack balance, JSR/RTL
  pairing, and DMA/HDMA register differences
- can explain why a patch is safe, not just produce plausible assembly
- can use z3cli's Oracle adapter surface without needing the full unfiltered MCP
  tool list

Strong eval behavior should move the model toward the `oracle` public slot.
Mixed behavior should keep it as the direct `oracle-qwen35-9b` candidate while
we harvest failure cases for DPO or a corrective SFT.

### z3cli Promotion Gate

Use the real z3cli session gate before promoting `oracle-qwen35-9b`:

```bash
python3 scripts/run_z3cli_oracle_promotion_eval.py \
  --prompt-pack /Users/scawful/src/training/evals/oracle_z3cli_promotion_holdout_v1.jsonl \
  --model oracle-9b-router \
  --mode manual \
  --workspace /Users/scawful/src/hobby/z3cli \
  --out reports/oracle-promotion-evals/oracle_qwen35_9b_promotion.jsonl
```

This runner launches `z3cli --serve`, watches streamed tool events, scores the
observed tool calls and arguments, and writes JSONL results. It exits `0` only
when every row passes. For already-captured chat sessions, use `--session
<path>`; session scoring ignores `oracle-prefetch-*` records by default so
runtime prefetch does not hide a missing model-emitted tool call.

Details live in `docs/oracle-z3cli-promotion-eval-gate.md`.

Windows note: keep the eval workspace pointed at `D:\src\hobby\z3cli` and set
`Z3CLI_ZELDA_WORKSPACE=D:\src\hobby\oracle-of-secrets` for Zelda tools. Use the
wrapper in `scripts/windows_oracle_9b_eval.ps1` so LM Studio loading, direct API
fallback, and serve-readiness settings stay consistent. On 2026-05-02 local /
2026-05-03 UTC, `oracle-9b-router` passed the full compact z3cli seed gate
12/12 and the targeted previously failing rows 3/3 after runtime hardening.
Treat it as seed-gate green, but do not promote it to the plain `oracle` slot
until a fresh hard gate also covers live Mesen2 state, ASAR compile repair,
65816 width/bank/JSR/JSL traps, and Oracle-vs-vanilla evidence boundaries.

## Dataset And Training Policy

Keep these data boundaries:

- Oracle/Zelda data belongs to z3cli and Oracle-series work.
- scawfulbot/avatar data belongs to the persona lane.
- Do not mix uncensored roleplay/NSFW data into Oracle, Farore, z3cli, or
  scawfulbot runs.
- For Zelda model improvement, prefer project-grounded traces, z3cli tool-use
  transcripts, ASAR compile/replay failures, repo retrieval failures, and
  hand-curated 65816 repair examples.

Aggressive future improvement should come from better samples and targeted
post-training:

- checkpoint failure mining
- ASAR compile hard negatives
- z3ed/Mesen tool-use transcripts
- repo-grounded repair examples
- DPO only after we have clear preference pairs
- possible continued pretraining only if SFT/DPO does not teach enough low-level
  ALTTP/codebase structure

## Open Follow-Ups

- Fix the training dashboard parser so nested eval loops are not displayed as
  the main train step.
- Fix Scawfulbot-side SSH probing separately; it is not part of the Zelda
  handoff, but it made the shared dashboard less trustworthy.
- Add an explicit z3cli command or doc snippet for importing the converted
  `oracle-qwen35-9b` GGUF into the local LM Studio catalog.
- Capture first Farore eval failures before deciding on DPO.
- Keep `oracle-coder` separate from this 9B candidate. `oracle-coder` is still
  the focused code-authoring worker lane, while `oracle-qwen35-9b` is the
  daily Oracle agent candidate.
