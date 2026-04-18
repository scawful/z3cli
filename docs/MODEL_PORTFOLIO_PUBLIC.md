# Public Model Portfolio Notes

z3cli exposes a **public routing contract** for model names while keeping
deployments and checkpoints private.

This page is now more operator-facing than public-sanitized. It keeps the
canonical Oracle model names, but it no longer tries to hide the concrete local
developer model variants that are useful in day-to-day z3cli work.

## What is exposed in this repo

- Canonical models:
  - `oracle` — `8B corrective Oracle · q4km`
  - `oracle-fast` — `8-9B fast Oracle · live alias`
- Heavy model:
  - `oracle-pro` — `27B switchhook Oracle · q4km`
- Direct local developer variants:
  - `qwen3-oracle-8b` / `oracle-q8` — `8B corrective Oracle · q8_0`
  - `nayru` / `nayru-q8` — `9B Qwen3.5 explainer · q8_0`
  - `farore` / `farore-q8` — `9B Qwen3.5 debug/FIM · q8_0`
  - `farore-q4km` — `9B Qwen3.5 debug/FIM · q4km`
  - `majora` / `majora-q4km` — `9B Qwen3.5 architecture · q4km`
  - `hylia` / `hylia-q8` — `9B Qwen3.5 lore/history · q8_0`
  - `hylia-q4km` — `9B Qwen3.5 lore/history · q4km`
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

- `oracle` is the canonical entry point for sustained Zelda work.
- `oracle-fast` is the intentionally narrower/faster quick model.
- `oracle-pro` is the explicit heavy-model opt-in and is not the default local path.
- The local Qwen3.5 specialist bench is intentionally visible in z3cli:
  `nayru`, `farore`, `farore-q4km`, `majora`, `hylia`, and `hylia-q4km`.
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
