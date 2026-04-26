# z3cli Protobuf Contracts

The protobuf tree is the schema root. Files are grouped by service domain, but
implementation code lives under `src/services/`.

The current rule is messages first, services later. Do not add proto `service`
definitions until there is a real multi-daemon transport boundary that needs
generated RPC stubs.

## Package And Layout

The draft contracts use one repo-level package:

- `package z3cli;`

There is no `v1` directory or package suffix yet. Add explicit versioning only
after the schema has an external compatibility boundary that justifies carrying
multiple versions.

Current draft files:

- `proto/common.proto`: shared enums and endpoint metadata.
- `proto/models.proto`: configured and runtime model records.
- `proto/inventory.proto`: cached runtime inventory snapshots.
- `proto/routes.proto`: route selection and health state.
- `proto/ui_events.proto`: UI-facing async events.

## Naming

Operator-facing route names should describe the inference route, not the
machine nickname:

- `oracle-pro-5090`: primary Windows 5090 LM Studio route.
- `oracle-pro-ssh`: SSH command-proxy fallback to the same host.
- `oracle-pro-vast`: remote Vast fallback.

Friendly aliases such as `home`, `home-ssh`, `vast`, and `pro` can remain
backcompat shortcuts, but new docs and UI should prefer canonical route names.

## Transport Mapping

For the Ink frontend, use JSON-RPC with proto JSON-shaped payloads:

```json
{"method":"route/select","params":{"route":"oracle-pro-5090"}}
{"method":"route/list","params":{}}
{"method":"route/status","params":{"route":"oracle-pro-5090"}}
{"method":"route/probe","params":{"route":"oracle-pro-ssh","timeoutMs":30000}}
{"method":"inventory/query","params":{"forceRefresh":false}}
{"method":"inventory/snapshot","params":{"route":"oracle-pro-5090"}}
{"method":"inventory/refresh","params":{}}
{"method":"models","params":{}}
```

Async convergence events are emitted as JSON-RPC notifications using proto-shaped fields
based on `proto/ui_events.proto`:

```json
{"method":"ui/event","params":{"kind":"UI_EVENT_KIND_ROUTE_SELECTED","routeName":"oracle-pro-5090","message":"Route set to oracle-pro-5090"}}
{"method":"ui/event","params":{"kind":"UI_EVENT_KIND_INVENTORY_UPDATED","routeName":"oracle-pro-5090","message":"Inventory updated"}}
```

The Python serve loop currently implements the direct `route/*` methods above
for the router seam and direct `inventory/*` methods for cached runtime
snapshots. Legacy slash-command transport remains available via
`{"method":"command","params":{"cmd":"/route","args":["oracle-pro-5090"]}}`.

Internal daemons can initially use stdio or Unix sockets. If the boundaries
stabilize and streaming/deadlines become valuable, add gRPC service definitions
in a separate `*_service.proto` file.
