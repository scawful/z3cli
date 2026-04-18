# Validation gates

Use these checkpoints before relying on the iOS client for real hacking sessions.

## 1. Contract / line parsing

- **Swift (local):** `cd ios/ZeldaRemoteCore && swift test` — exercises `ParsedRPC` against sample NDJSON lines.
- **Manual:** compare decoded fields with [`frontend/src/ipc/protocol.ts`](../../frontend/src/ipc/protocol.ts) whenever serve adds a new notification.

## 2. Bridge handshake

- **Python:** `tests/test_ws_bridge_args.py` — argument parsing and token requirement.
- **Manual:** start bridge with a token; connect once **without** `Authorization: Bearer …` and expect close **4001**; connect with correct header and expect a `ready` frame after child spawn.

## 3. End-to-end (Tailscale or LAN)

1. Host: LM Studio listening on `127.0.0.1:1234` (or env overrides).
2. Host: `python -m z3cli --bridge --bridge-host 0.0.0.0 --bridge-port 8765 --bridge-token SECRET -- …serve args…`
3. Phone (or Simulator): open app → Connect → `ws://<tailscale-ip>:8765` + token.
4. Send a short chat; confirm streaming `text` / `done`.
5. Trigger a tool that requires permission; confirm sheet + `tool/decision` unblocks the host.

## 4. Failure modes

| Scenario | Expected |
|----------|----------|
| Kill bridge mid-stream | WebSocket error; client should reset streaming state; host child terminated |
| Second concurrent `chat` while one active | Serve returns error notification; client should show `error` |
| Idle proxy / reverse proxy | No premature HTTP timeout closing WS during long tool calls |

## 5. Security

- Never commit real `Z3CLI_BRIDGE_TOKEN` values.
- Treat the token like a password; rotate if leaked.
- Prefer tailnet-only bind addresses unless you explicitly need LAN.
