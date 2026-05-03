# Public Model Portfolio Notes

z3cli exposes an operator-facing routing contract for model names while keeping
private deployment details out of the repo.

This page is now more operator-facing than public-sanitized. It keeps the
canonical Oracle model names, but it no longer tries to hide the concrete local
developer model variants that are useful in day-to-day z3cli work.

## What is exposed in this repo

- Canonical models:
  - `oracle` — installed `14B Oracle v8 · q4km` local default
  - `oracle-9b-router` — fast `oracle-9b-candidate-v5` lane with a 14B teacher-router runtime guard
  - `oracle-fast` — lower-latency corrective Oracle slot, hidden until its GGUF is restored
  - `oracle-pro` — advanced/manual alias for the current `14B Oracle-Pro v8 · q4km` lane
- Heavy model:
  - `oracle-mythic` — `27B switchhook Oracle · q4km` manual-only
- Direct local developer variants:
  - `oracle-qwen35-9b` — configured 9B Oracle Qwen3.5 lane, hidden until its GGUF is installed
  - `din` — installed Din optimizer v4
  - `nayru` / `nayru-q8` — installed Nayru explainer v9 q8_0
  - `navi` / `navi-q8` — installed Navi FIM/debug lane backed by Farore v5 q8
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

- `oracle` is the real pinned local Oracle model today and resolves to the installed `qwen3-oracle-14b-v8-q4km` GGUF.
- `oracle-9b-router` is the practical fast-lane candidate: it keeps 9B v5 as
  the runtime model and injects teacher-router guardrails for known weak spots
  selected from the 14B v8 eval evidence.
- `oracle-fast` is configured but stays hidden until the corrective 8B GGUF is restored locally.
- `oracle-pro` is an advanced/manual alias for the current critical-safe local pro lane.
- `oracle-mythic` is the explicit heavy-model opt-in and should only be loaded when that path is intentional.
- `oracle-qwen35-9b` stays as the configured 9B Oracle Qwen3.5 lane, but it should not appear in the normal picker until the matching GGUF exists in LM Studio.
- The default z3cli model list is intentionally small:
  `oracle`, `din`, `nayru`, and `navi` when those entries are installed or
  available.
- `veran`, `hylia`, and `majora` are retired from the active z3cli picker and
  catalog and from the runtime adapter registry. Their old adapter files may
  remain as historical reference code, but they are no longer part of the
  primary model family.
- `oracle-pro`, `qwen3-oracle-8b`, and `navi-q4km` stay available through
  `/models catalog advanced` when installed, not the default picker.
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
