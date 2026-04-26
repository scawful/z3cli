# C++ Router Daemon Extraction Gate

This checklist defines the *minimum* readiness criteria for extracting the C++ router daemon from the Python serve loop.

The goal is to keep the router **cached-state only**: it acknowledges route changes immediately and relies on inventory snapshots for convergence and health.

## Gate Criteria (must all be true)

- **Inventory sidecar is the default probe owner**
  - Python serve loop can use an out-of-process inventory backend (`services.inventory.daemon.main`) for `inventory/*`.
  - Sidecar failure has a deterministic fallback that does not break route selection or inventory reads.

- **`inventory/query` default semantics are stable**
  - No filter → returns **all canonical routes** (non-advanced).
  - `inventory/snapshot` / `inventory/refresh` with no filter → targets **active route only**.

- **Operator events support async convergence**
  - `UI_EVENT_KIND_INVENTORY_REFRESHING` is emitted before refresh work begins.
  - `UI_EVENT_KIND_INVENTORY_UPDATED` is emitted on completion with the final snapshot attached.

- **Ack-before-slow-work is test-covered**
  - Route selection acknowledges before inventory probing/refresh completes.
  - Sidecar mode has parity coverage and a failure/fallback test.

- **Session handoff for “active” context**
  - Inventory sidecar and native router accept `session/sync` so `active` + default inventory targets match the
    Python serve loop without guessing from env alone.

## Router Constraints (non-negotiable)

- **No probes in router**: the router daemon must not call LM Studio / llama.cpp, SSH, file scanners, LSP, or tool surfaces.
- **Inventory is an input**: router consumes cached `InventorySnapshot` payloads (TTL + generation) and emits UI convergence events.
- **Cancellation is first-class**: request IDs and cancellation must be wired end-to-end at the router boundary.

## What to build next once the gate is green

- Choose a router binary name.
- Extract JSON-RPC transport into the C++ router daemon (stdio first).
- Implement only:
  - `/route list`, `/route select`, `/route status`
  - `ui/event` emission (no probing)
