# z3cli Daemon Runtime Plan

This plan defines the direction for moving fragile serving/routing work out of
the Python UI loop. The repo should be organized by service boundary, not by the
language used to implement a slice. Implementation code lives under
`src/services/`; schemas live under top-level `proto/`.

## Principles

- Protobuf is the source of truth for daemon contracts.
- Transport stays separate from schema. Start with JSON-RPC and proto JSON
  payloads; add gRPC only when a daemon boundary needs generated RPC stubs.
- Route selection must acknowledge immediately. Slow inventory, model loading,
  SSH, LSP, shell, or file-context work must emit async convergence events.
- Service folders own handlers, domain libraries, tests, and daemon entrypoints.
  Implementation language is local to a service. Protobuf contracts live in
  top-level `proto/`.
- C++ code follows Google C++ style and the Yaze house style: structural,
  functional, low ceremony, testable units, explicit status returns, and useful
  CLI surfaces.
- Python remains the right tool for training, evals, Hugging Face datasets,
  prompt-pack scoring, exploratory scripts, and the initial tool-service
  implementation.

## Daemon Boundaries

The router daemon is the front door. Its binary name is TBD. It owns JSON-RPC,
`/route`, chat admission, request IDs, cancellation, active route state, and UI
notifications. It must read cached state only and must not call `lms`, SSH,
file scanners, LSP, or model inventory directly.

The inventory daemon owns runtime discovery. Its binary name is TBD. It polls
LM Studio, llama.cpp, hostd, SSH availability, loaded models, aliases, VRAM,
and health. It publishes cached snapshots with TTLs and generation numbers.

The model daemon owns inference transport once provider logic needs extraction.
Its binary name is TBD. It normalizes OpenAI-compatible HTTP/SSE, SSH command
proxy behavior, request deadlines, retries, and cancellation.

The tool daemon stays Python initially. Its binary name is TBD. It owns MCP
tools, z3ed/emulator helpers, shell execution, focus/LSP enrichment, and
write-review controls.

The session daemon is optional. Extract it only if JSONL transcript writes,
compaction, stats, and export-training logic start cluttering the router. Its
binary name is TBD.

## Operator Commands

The primary UX should be route-oriented:

```text
/route
/route list
/route list advanced
/route oracle-pro-5090
/route oracle-pro-ssh
/route oracle-pro-vast
/route smoke [route]
/route health [route]
```

Model catalog commands stay model-oriented:

```text
/models
/models loaded
/models catalog
/models catalog advanced
/models routes
/models routes advanced
/models load <model>
/models unload <model>
```

Backcompat aliases stay available but should not be the canonical docs/UI path:

```text
/use home      -> /route oracle-pro-5090
/use home-ssh  -> /route oracle-pro-ssh
/use vast      -> /route oracle-pro-vast
```

`/models` and `/route list` should stay operator-focused and canonical.
Internal registry nodes, model fallback names, quant variants, and legacy
aliases belong behind `catalog advanced` / `routes advanced` so normal
selection does not become a dump of the whole model registry.

## Implementation Style

- Use C++23, CMake presets, `clang-format`, and Google C++ style as the base.
- Prefer free functions, small structs, and explicit dependency structs over
  inheritance-heavy service objects.
- Use `absl::Status` and `absl::StatusOr<T>` for fallible work. Avoid exceptions
  across daemon boundaries.
- Keep daemon state explicit: `RouteState`, `InventorySnapshot`,
  `RequestContext`, `Deadline`, and `CancellationToken` should be data first.
- Put helpers in anonymous namespaces in `.cc` files. Keep headers narrow.
- Use structured logging with request IDs, route names, backend names, and
  elapsed milliseconds. Logs should explain what blocked or degraded.
- Prefer pure parsing/normalization functions that are easy to unit test.
- Keep agentic controls first-class: request IDs, cancellation, dry-run/probe
  mode, health events, and explicit degraded states.
- Organize code as small libraries with colocated tests under the owning
  service. Do not create a repo-level language folder or a global test tree for
  service code.
- Keep API handlers thin and predictable: `service/<api_name>_handler.cc`
  adapts wire/API requests to domain libraries; it should not own probing,
  routing, inventory, or session business logic.

## Service-First Layout Target

```text
src/
  services/
    README.md
    shared/
      common/
        deadline.{h,cc}
        deadline_test.cc
        logging.{h,cc}
        proto_json.{h,cc}
        proto_json_test.cc
    router/
      route/
        route_registry.{h,cc}
        route_registry_test.cc
        route_state.{h,cc}
        route_state_test.cc
      service/
        route_handler.{h,cc}
        route_handler_test.cc
        models_handler.{h,cc}
        models_handler_test.cc
      daemon/
        main.cc
    inventory/
      inventory/
        inventory_cache.{h,cc}
        inventory_cache_test.cc
      probes/
        studio_probe.{h,cc}
        studio_probe_test.cc
        llamacpp_probe.{h,cc}
        llamacpp_probe_test.cc
      service/
        inventory_handler.{h,cc}
        inventory_handler_test.cc
      daemon/
        main.cc
    model/
      service/
        completion_handler.{h,cc}
        completion_handler_test.cc
      daemon/
        main.cc
    tool/
      service/
        tool_handler.py
        tool_handler_test.py
      adapters/
        mcp.py
        z3ed.py
        workspace_context.py
proto/
  common.proto
  models.proto
  inventory.proto
  routes.proto
  ui_events.proto
```

Domain libraries should expose functional APIs such as
`SelectRoute(RouteState*, const SelectRouteRequest&)`,
`NormalizeLoadedModel(const RawModelEntry&)`, or
`UpdateInventoryCache(InventoryCache*, InventorySnapshot)`. Handler files should
mostly validate request shape, call those APIs, map status/errors to the chosen
transport, and attach request IDs for logging.

## Contract Files

The initial proto messages live directly under `proto/` and use the single
draft package `z3cli`. They intentionally do not define services yet. When a
transport boundary needs generated stubs, add a separate `*_service.proto` file
instead of mixing service definitions into the message-only contracts. Do not
add versioned package suffixes until the schema has a real external
compatibility boundary.

## Testing

- Proto contracts compile with `protoc`.
- Golden proto JSON fixtures cover route selection, inventory snapshots, and UI
  route events.
- Router unit tests use fake inventory/model/tool clients.
- Integration tests verify that `/route oracle-pro-5090` acknowledges before
  inventory refresh or model probe work starts.
- CLI smoke tests cover the final router binary name once selected: serve over
  stdio, route list, route smoke `oracle-pro-5090`, and cancellation.

## First Implementation Slice

1. Add `/route` in Python as the canonical command and keep `/use` as an alias.
2. Move route/model payloads toward the proto-shaped fields.
3. Generate or validate Python protobuf bindings for tests only.
4. Build the inventory daemon or a Python inventory sidecar next, because
   inventory is the current source of route-switch timeouts.
5. Build the router daemon in C++ after route schema and UI events stabilize,
   choosing the binary name at that point.

Current progress: the Python serve loop now exposes direct `route/list`,
`route/select`, `route/status`, and `route/probe` JSON-RPC methods using
proto-JSON shaped route payloads. Slash commands remain as compatibility UI
commands, while the direct methods are the seam future daemons and clients
should target.

The serve loop also has an initial inventory seam: `inventory/query`,
`inventory/snapshot`, and `inventory/refresh` return cached proto-JSON shaped
`InventorySnapshot` payloads. Only the active route is actively probed by this
Python implementation; non-active routes are represented as configured but
unknown until a real inventory daemon polls every endpoint.

## Status (2026-04-26)

The inventory-first slice has landed in the current tree:

- Golden proto-JSON fixtures exist for route/inventory/UI events:
  - `tests/fixtures/proto_json_golden/`
  - `tests/test_proto_json_golden.py`
- Inventory probing now has a service-owned runtime:
  - `src/services/inventory/runtime.py`
- A minimal Python inventory sidecar entrypoint exists (stdio JSON-RPC):
  - `src/services/inventory/daemon/main.py`
- The serve loop reads inventory through a client seam:
  - `src/app/inventory_client.py`
- Route selection emits async convergence notifications:
  - JSON-RPC notification method: `ui/event` (proto-shaped, based on `proto/ui_events.proto`)

## Next Steps

1. Wire the inventory sidecar as a real out-of-process backend for the serve loop.
   - Extend `src/app/inventory_client.py` with a transport mode:
     - spawn `python -m services.inventory.daemon.main` (or equivalent) and speak NDJSON JSON-RPC
     - or connect via a Unix socket once introduced
   - Keep in-process fallback for tests and bootstrap safety.

2. Expand inventory polling beyond “active route” semantics.
   - Poll all configured route entries on a cadence.
   - Ensure `InventorySnapshot.generation` increments monotonically as new snapshots arrive.

3. Make the `ui/event` stream operator-meaningful.
   - Emit `UI_EVENT_KIND_INVENTORY_REFRESHING` before a refresh and
     `UI_EVENT_KIND_INVENTORY_UPDATED` on completion.
   - Optional: add `UI_EVENT_KIND_ROUTE_HEALTHY/DEGRADED/UNAVAILABLE` based on snapshot health.

4. Only after the above stabilizes: extract the C++ router daemon.
   - Router must remain “cached-state only” and depend on inventory snapshots rather than probes.
