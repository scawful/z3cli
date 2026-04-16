# Public Model Portfolio Notes

z3cli exposes a **public routing contract** for model names while keeping
deployments and checkpoints private.

## What is exposed in this repo

- Canonical lanes:
  - `oracle` — primary long-form Zelda workflow lane
  - `oracle-fast` — lower-latency fast path
- Legacy compatibility aliases are accepted for continuity:
  - `oracle-main-plan`, `oracle-main-act`, `oracle-tools`
  - `switchhook`, `switchhook-plan`, `switchhook-act`
- Specialist names are visible only as stable aliases that map to internally
  configured implementations at runtime.

## Why this split is intentional

- The repo documents the **behavioral contract** (commands, modes, aliases, routing)
  and not the underlying private model artifacts.
- Alias names and routing semantics can stay stable while checkpoints evolve.
- This lets you show capability progress publicly without exposing:
  - model IDs / checkpoint names
  - provider credentials
  - training data provenance
  - proprietary evals and rollout gates

## Where to publish full detail

For deeper technical disclosure (benchmarks, eval methodology, hardware stack,
or training notes), use a separate private/private-by-default destination such as
`halext.org` and link to a public summary from this repository.
