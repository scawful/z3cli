# Z3CLI Model Systems Lab

### Experimental log for a model-first Zelda tooling stack

This is an active engineering lab for routing, model specialization, and tool
coherence in `z3cli`. It is intentionally **experimental** and written as a
public-facing status page.

## Overview

`z3cli` ships with a public routing contract for model aliases, while private
implementations remain intentionally out-of-band. The goal is to make the
surface area stable enough for tooling and docs while keeping internals
iterative.

- `oracle` is the canonical Zelda workflow lane
- `oracle-fast` is the lower-latency lane for quick checks and light edits
- legacy compatibility aliases still resolve so old notes/scripts do not break

## Experimental Focus

▲ Contract stability over implementation churn  
▲ Behavioral consistency across modes and fast/slow lanes  
▲ Observability on model choice, routing, and tool call outcomes  
▲ Safe incremental rollout of new specialists and aliases  

## What the page is *not* doing

- It is not publishing private model IDs, checkpoints, or secrets.
- It is not presenting fixed benchmarks as final truth; results are
  intentionally framed as running experiments.
- It is not a static product launch narrative; this is ongoing work.

## Current Experiments

- Compatibility pass-through:
  - legacy aliases (`oracle-main-plan`, `oracle-main-act`, `oracle-tools`,
    `switchhook`, `switchhook-plan`, `switchhook-act`) remain accepted
- Routing simplification:
  - user-facing modes are `manual`, `oracle`, `orchestrator`, `broadcast`
- Safety and traceability:
  - resumable sessions, persistent workspace/tool state, and explicit write
    reviews in serve mode
- Public contract shaping:
  - only stable aliases and behaviors are committed in public docs

## Early signals worth showing

▲ Local command/repl and serve flows share the same lane model (`oracle` / `oracle-fast`)  
▲ Model-scoped history prevents context bleed between specialists  
▲ Legacy names map to canonical lanes without confusing end users  
▲ The project is already usable as a public case study for model routing in
  ROM-hacking tooling

## Live links

- GitHub summary: [`MODEL_PORTFOLIO_PUBLIC.md`](/docs/MODEL_PORTFOLIO_PUBLIC.md)
- CLI usage and command inventory: [`README.md`](/README.md)
- Orchestration plan notes (publicly safe): [`docs/orchestration-architecture.md`](/docs/orchestration-architecture.md)

## Suggested `halext.org` publication block

Use this as the content body for a `halext.org/labs/Z3CLI/` page entry, with a
different title if you prefer:

**Title:** `Z3CLI Model Systems Lab`  
**Slug:** `Z3CLI-Model-Lab`  
**Summary:** Experimental progress on model routing for Zelda development tools.

```json
{
  "slug": "Z3CLI-Model-Lab",
  "title": "Z3CLI Model Systems Lab",
  "summary": "An experimental log for routing, model specialization, and tool-aware workflows in z3cli.",
  "is_published": true,
  "theme": {
    "layout": "markdown",
    "accent": "#8b5cf6"
  },
  "nav_links": [
    {
      "label": "GitHub",
      "url": "https://github.com/scawful/z3cli",
      "description": "Public repo and changelog"
    },
    {
      "label": "Portfolio Notes",
      "url": "https://github.com/scawful/z3cli/blob/master/docs/MODEL_PORTFOLIO_PUBLIC.md",
      "description": "Public routing contract and safe project notes"
    }
  ],
  "sections": [
    {
      "type": "markdown",
      "title": "Overview",
      "body": "z3cli exposes a public model-routing contract for Zelda-specific workflows while keeping private checkpoints and provider details out of public docs."
    },
    {
      "type": "markdown",
      "title": "Experimental Focus",
      "body": "Contract stability, routing consistency, lightweight telemetry, and compatibility-first alias management are under active iteration."
    },
    {
      "type": "markdown",
      "title": "Current Lanes",
      "body": "- `oracle`: primary long-form lane\n- `oracle-fast`: latency-focused quick lane\n- legacy aliases preserved as compatibility adapters"
    }
  ]
}
```

If you want this to be truly identical to the old `Oracle/` rendering flow, I can
also generate the matching legacy `halext_api_client`/`site_pages` payload in a
curl-ready version once we confirm the exact `type` fields your current `halext`
front-end expects for Labs display.
