# Public Model Portfolio Notes

z3cli exposes a **public routing contract** for model names while keeping
deployments and checkpoints private.

This page is now more operator-facing than public-sanitized. It keeps the
canonical Oracle model names, but it no longer tries to hide the concrete local
developer model variants that are useful in day-to-day z3cli work.

## What is exposed in this repo

- Canonical models:
  - `oracle-fast` — `8B corrective Oracle · q4km`
  - `oracle` — reserved mainline slot hidden until installed
  - `oracle-pro` — `14B Oracle-Pro · q4km` current local pro lane
- Heavy model:
  - `oracle-mythic` — `27B switchhook Oracle · q4km` manual-only
- Direct local developer variants:
  - `qwen3-oracle-8b` / `oracle-q8` — `8B corrective Oracle · q8_0`
  - `nayru` / `nayru-q8` — `9B Qwen3.5 explainer · q8_0`
  - `farore` / `farore-q8` — `9B Qwen3.5 debug/FIM · q8_0`
  - `farore-q4km` — `9B Qwen3.5 debug/FIM · q4km`
  - `majora` / `majora-q4km` — `9B Qwen3.5 architecture · q4km`
  - `hylia` / `hylia-q8` — `9B Qwen3.5 lore/history · q8_0`
  - `hylia-q4km` — `9B Qwen3.5 lore/history · q4km`
- Internal callable worker:
  - `oracle-coder` — internal-only code authoring worker, not a normal picker target
- Legacy compatibility aliases still resolve quietly, but the real working names are the ones above.

## Public capabilities snapshot

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

## Public one-minute summary

- `oracle-fast` is the real pinned local Oracle model today.
- `oracle` is the reserved mainline slot and stays hidden until LM Studio can actually load it.
- `oracle-pro` is the current local pro lane.
- `oracle-mythic` is the explicit heavy-model opt-in and is not part of the simple primary picker.
- The local Qwen3.5 specialist bench is intentionally visible in z3cli:
  `nayru`, `farore`, `farore-q4km`, `majora`, `hylia`, and `hylia-q4km`.
- `qwen3-oracle-8b` stays available as an alternate catalog entry, not part of the simple main Oracle surface.
- `oracle-coder` stays internal and is meant to be invoked by `oracle`, not selected as a public-facing working model.
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
