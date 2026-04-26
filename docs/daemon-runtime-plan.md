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
- Inventory sidecar transport is implemented (optional, with fallback):
  - `src/app/inventory_client.py` supports a `sidecar` mode that spawns the inventory daemon
    and speaks NDJSON JSON-RPC over stdio.
  - If the sidecar fails to start or errors mid-request, the client falls back to in-process
    inventory reads so route selection and inventory reads keep working.
- Inventory query semantics are now stable across serve loop and sidecar:
  - `inventory/query` with no route filter returns *all canonical routes* (non-advanced).
  - `inventory/snapshot` / `inventory/refresh` with no route filter targets the *active route*.
- Inventory refresh lifecycle events are implemented:
  - `UI_EVENT_KIND_INVENTORY_REFRESHING` is emitted before refresh work begins.
  - `UI_EVENT_KIND_INVENTORY_UPDATED` is emitted on completion with the snapshot payload attached.
- Sidecar + event sequencing tests exist:
  - `tests/test_inventory_sidecar_integration.py`

## Next Steps

1. Expand inventory polling beyond “active route” semantics.
   - The inventory runtime should poll all configured route entries on a cadence.
   - Ensure `InventorySnapshot.generation` increments monotonically as new snapshots arrive.

2. Tighten “router extraction gate” readiness criteria.
   - Keep the router daemon “cached-state only” and dependent on inventory snapshots rather than probes.
   - See `docs/router-extraction-gate.md` for the explicit checklist.

3. Start C++ router extraction *once the gate is green*.
   - Choose the router binary name at extraction time.
   - First C++ slice should implement JSON-RPC over stdio + `/route list|select|status` + `ui/event` emission,
     and must not probe any backends directly.

### Native router daemon (experimental)

Source lives under `src/services/router/daemon_native/` and builds `z3cli-routerd`.

```bash
cmake -S src/services/router/daemon_native -B src/services/router/daemon_native/build
cmake --build src/services/router/daemon_native/build -j8
```

The binary speaks NDJSON JSON-RPC on stdio, reuses the Python inventory sidecar for snapshots, and targets
the same `route/list` envelope as `app.serve._route_list_payload` (`active`, `entries`, `active_route`, `routes`).

Clangd picks up `compile_commands.json` via `src/services/router/daemon_native/.clangd` after configuring the
build directory above.

### Inventory snapshot carry fields

`InventorySnapshot` JSON now includes optional `route` and `routeEntry` objects alongside the existing probe
fields. These are derived from `services.router.route.contract.route_from_entry` so out-of-process routers can
reuse the exact proto-JSON route shape without re-loading `chat_registry.toml`.

**Forward compatibility:** treat inventory snapshots and route payloads as semi-open JSON. Unknown fields may
appear as contracts evolve; clients should ignore keys they do not understand.

### `session/sync` (router ↔ inventory)

Parent processes (or the native router daemon) can push the same `active` block as `app.serve._route_list_payload`
so default `inventory/snapshot` / `inventory/refresh` (no route filter) resolve the **same** active route as the
serve loop.

JSON-RPC method: `session/sync`

Params (all optional except as noted):

- `active`: object with `backend`, `model`, `studio_node`, `llamacpp_node` (same strings as the serve loop UI)
- `activeRoute` or `active_route`: canonical route name (e.g. `oracle-pro-5090`)

The native router (`z3cli-routerd`) implements `session/sync`, merges `active` on top of `Z3CLI_*` env defaults,
updates its cached `active_route`, and forwards the same request to the inventory sidecar.

## Inventory Transport Toggle (serve loop)

The serve loop can route inventory calls through the out-of-process inventory sidecar by setting:

- `Z3CLI_INVENTORY_TRANSPORT=auto` (default): prefer sidecar, fall back to in-process on failure
- `Z3CLI_INVENTORY_TRANSPORT=sidecar`: force sidecar (still falls back per-request for safety)
- `Z3CLI_INVENTORY_TRANSPORT=inprocess`: disable sidecar and always use in-process inventory
