# Public Model Portfolio Notes

z3cli exposes a **public routing contract** for model names while keeping
deployments and checkpoints private.

This page is safe to publish publicly and acts as a portfolio note for
`github.com/scawful/z3cli` or a future `halext.org` write-up.

## What is exposed in this repo

- Canonical lanes:
  - `oracle` — primary long-form Zelda workflow lane
  - `oracle-fast` — lower-latency fast path
- Legacy compatibility aliases are accepted for continuity:
  - `oracle-main-plan`, `oracle-main-act`, `oracle-tools`
  - `switchhook`, `switchhook-plan`, `switchhook-act`
- Specialist names are visible only as stable aliases that map to internally
  configured implementations at runtime.

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

- The repo documents the **behavioral contract** (commands, modes, aliases, routing)
  and not the underlying private model artifacts.
- Alias names and routing semantics can stay stable while checkpoints evolve.
- This lets you show capability progress publicly without exposing:
  - model IDs / checkpoint names
  - provider credentials
  - training data provenance
  - proprietary evals and rollout gates

## Public one-minute summary

- `oracle` is the canonical entry point for sustained Zelda work.
- `oracle-fast` is intentionally narrower/faster for quick interactions.
- Legacy names still resolve to avoid breakage in existing notes/scripts.
- Specialists are accessible through the same catalog contract but their concrete
  definitions are intentionally runtime-local.

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
