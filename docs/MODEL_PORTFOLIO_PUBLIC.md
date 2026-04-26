# Public Model Portfolio Notes

z3cli exposes an operator-facing routing contract for model names while keeping
private deployment details out of the repo.

This page is now more operator-facing than public-sanitized. It keeps the
canonical Oracle model names, but it no longer tries to hide the concrete local
developer model variants that are useful in day-to-day z3cli work.

## What is exposed in this repo

- Canonical models:
  - `oracle-fast` — `8B corrective Oracle · q4km`
  - `oracle` — reserved mainline slot hidden until installed
  - `oracle-pro` — `14B Oracle-Pro v8 · q4km` current critical-safe local pro lane
- Heavy model:
  - `oracle-mythic` — `27B switchhook Oracle · q4km` manual-only
- Direct local developer variants:
  - `oracle-qwen35-9b` — `Oracle daily 9B · q4km` (Farore-trained debug/tool-use overlay)
  - `din` — `Din optimizer · Qwen3 8B`
  - `nayru` / `nayru-q8` — `Nayru explainer · q8_0`
  - `navi` / `navi-q8` — `Navi FIM/debug · q8`
  - `navi-q4km` and `qwen3-oracle-8b` / `oracle-q8` — advanced catalog variants
- Internal callable worker:
  - `oracle-coder` — internal-only code authoring worker, not a normal picker target
  - `oracle-coder-pro` — hidden Qwen3-Coder 30B-A3B FP8 vLLM sidecar for Oracle-Pro patch synthesis
  - `oracle-reasoner-27b` — hidden Qwen3.6 27B FP8 vLLM sidecar for model/catalog/training strategy review
- Legacy compatibility aliases still resolve quietly. `farore`, `farore-q8`,
  and `farore-q4km` now resolve to the Navi autocomplete/debug entries so the
  Farore training-run label does not collide with FIM helper naming.

## Operator Capabilities Snapshot

- Local-first interactive workflow with model switching, resumable sessions, and
  model-scoped context history.
- Mode-based routing (`manual`, `oracle`, `orchestrator`, `broadcast`) to keep
  simple and predictable interactions.
- Tooled coding workflow support in the command/repl/serve stack:
  read-only symbol workflows, scoped write verification, and optional
  post-write diff review.
- Runtime telemetry and history features suitable for debugging and progress
  tracking without exposing private keys or checkpoints.

## Why this split is intentional

- The repo still documents the behavioral contract first, but for local
  operator use it now also exposes the concrete model IDs and quant variants.
- Alias names and routing semantics can still stay stable while checkpoints
  evolve.

## Operator One-Minute Summary

- `oracle-fast` is the real pinned local Oracle model today.
- `oracle` is the reserved mainline slot and stays hidden until LM Studio can actually load it.
- `oracle-pro` is the current critical-safe local pro lane.
- `oracle-mythic` is the explicit heavy-model opt-in and should only be loaded when that path is intentional.
- `oracle-qwen35-9b` is the daily 9B Oracle Qwen3.5 lane — promoted from candidate after the Farore-labeled training run landed cleanly. Plain `oracle` stays reserved for the eventual 14B mainline; do not collapse the two.
- The default z3cli model list is intentionally small:
  `oracle-fast`, `oracle-qwen35-9b`, `oracle-pro`, `din`, `nayru`, and
  `navi` when those entries are installed or available.
- `veran`, `hylia`, and `majora` are retired from the active z3cli picker and
  catalog and from the runtime adapter registry. Their old adapter files may
  remain as historical reference code, but they are no longer part of the
  primary model family.
- `qwen3-oracle-8b` and `navi-q4km` stay available through
  `/models catalog advanced`, not the default picker.
- `oracle-coder` stays internal and is meant to be invoked by Oracle-family parents, not selected as a top-level working model.
- `oracle-coder-pro` and `oracle-reasoner-27b` are also internal-only, but they
  give Oracle-Pro heavier delegated authoring and long-context analysis lanes
  when the matching vLLM endpoints are running.
- Operationally, `medical-mechanica` WSL2 + RTX `5090` is the primary local
  Oracle/scawfulbot host, Mac is the control plane, and Vast is the fallback
  when the shared desktop cannot spare the GPU.
- The concrete definitions are local and developer-oriented rather than hidden.

## Where to publish full detail

For deeper technical disclosure (benchmarks, eval methodology, hardware stack,
or training notes), use a separate private/private-by-default destination such as
`halext.org` and link to a public summary from this repository.

Suggested `halext.org` page structure:

1. Purpose and value
   - "z3cli is a model-first Zelda tooling stack for local and cloud-capable
     editing workflows."
2. Public architecture
   - routing contract (`oracle`, `orchestrator`, specialists)
3. Reliability and safety
   - session persistence, alias compatibility, manual opt-in behavior
4. Practical examples
   - `oracle` planning prompt
   - `oracle-fast` verification/checking prompt
5. Roadmap
   - upcoming routing modes, observability, and catalog expansion
