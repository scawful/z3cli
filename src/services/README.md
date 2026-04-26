# z3cli Services

This tree is organized by service boundary, not implementation language.
Handlers, libraries, tests, and daemon entrypoints should live under the service
that owns them. Protobuf contracts live in the top-level `proto/` tree.

## Layout

- `src/services/router`: route selection, chat admission, JSON-RPC, request IDs,
  cancellation, and UI notification fanout.
- `src/services/inventory`: runtime discovery, health snapshots, loaded model
  inventory, and cache publishing.
- `src/services/model`: inference transport once provider logic moves out of
  the CLI loop.
- `src/services/tool`: MCP/z3ed/workspace tooling; initially Python.
- `src/services/shared`: cross-service utilities that are truly shared.

## Rules

- Keep implementation code service-owned. Do not add top-level language folders
  such as `cpp/`.
- Keep tests colocated with the service library or handler they verify.
- Keep handlers thin: `service/<api_name>_handler.cc` or equivalent should
  adapt wire requests to domain libraries, not own business logic.
- Keep proto schemas in `proto/` until the schema count or ownership complexity
  justifies subfolders.
- Python service seams should follow the same ownership rule: small contract
  and cache modules live under the owning service until a C++ daemon replaces
  them.
