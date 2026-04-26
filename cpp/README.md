# z3cli C++ daemons (experimental)

This folder hosts early C++ daemon extraction work.

## Build

```bash
cmake -S cpp -B cpp/build
cmake --build cpp/build -j
```

Outputs:
- `cpp/build/z3cli-routerd`

## Run (stdio NDJSON JSON-RPC)

`z3cli-routerd` reads NDJSON JSON-RPC requests from stdin and writes responses/notifications to stdout.
