# iOS Zelda Remote — reuse inventory

This document maps the existing z3cli frontend to what an iOS (SwiftUI) client can reuse vs what must be reimplemented.

## Summary

| Area | Reuse on iOS | Notes |
|------|----------------|-------|
| Wire contract (`chat`, `command`, `status`, `models`, `cancel`, `shutdown` + NDJSON notifications) | **Yes** | Source of truth: [`frontend/src/ipc/protocol.ts`](../../frontend/src/ipc/protocol.ts). Mirror as Swift `Codable` with snake_case JSON keys. |
| Event → UI state machine | **Yes (port)** | [`frontend/src/hooks/useBackend.ts`](../../frontend/src/hooks/useBackend.ts): `ready`, `message`, `text`, `thinking`, `tool_call`, `tool_result`, `done`, `error`, `tool/permission_request`. Port to `ObservableObject` / reducer-style updates. |
| JSON-RPC request/response correlation | **Yes (port)** | [`frontend/src/ipc/backend.ts`](../../frontend/src/ipc/backend.ts): incrementing `id`, `pending` map, `request` vs `notify`. |
| Slash commands & normalization | **Partial** | [`frontend/src/commands/index.ts`](../../frontend/src/commands/index.ts): reuse **semantics** for commands that only call `sendCommand`; exclude `executeShell`, `!` shell, `rg`/`find`, and any `node:child_process` usage. |
| Ink components (`App`, `PromptInput`, bubbles, etc.) | **No** | Terminal-only (`ink`, `useInput`, TTY). |
| Settings persistence (`~/.config/...`) | **No** | Replace with `UserDefaults` / app group on iOS. |
| Markdown pipeline (`marked-terminal`) | **No** | Use SwiftUI `AttributedString` / Markdown or a native renderer. |
| Spawn `python -m z3cli --serve` from the phone | **No** | iOS cannot run the Python backend locally like the CLI. Use a **host bridge** (see [`03-bridge.md`](./03-bridge.md)). |

## File-level map

### High reuse (contract + behavior)

- **`frontend/src/ipc/protocol.ts`** — `JsonRpcRequest`, `JsonRpcResponse`, `JsonRpcNotification`, `BackendEvent`, `Message`, `AppConfig`, `ModelInfo`. iOS models should stay aligned with Python `serve.py` payloads.
- **`frontend/src/hooks/useBackend.ts`** — `normalizeBackendMessage`, `permissionRuleKey`, streaming/cancel/permission flows. **Port**, do not import from TS on device.
- **`frontend/src/ipc/backend.ts`** — Request/notify/cancel/stop behavior; swap stdio for WebSocket transport.

### Low / no reuse (runtime or UI)

- **`frontend/src/index.tsx`** — Node entry, Python path resolution, Ink `render`.
- **`frontend/src/components/*.tsx`** — All Ink UI.
- **`frontend/src/hooks/useSettings.ts`** — Node `fs`, home-dir config paths.
- **`frontend/src/components/PromptInput.tsx`** — TTY, `readline`, `execFile("rg")`, workspace file discovery.

### Backend alignment

- **`z3cli/app/serve.py`** — stdin/stdout NDJSON loop; same messages must pass through the bridge unchanged.
- **`z3cli/core/session.py`** — Session files on the **host**; iOS triggers `/resume` etc. via `command`.

## Split rule for new shared work

Anything that touches **`node:*`**, **`process.*`**, **`ink`**, or **TTY** stays out of the Swift package. The Swift module [`ios/ZeldaRemoteCore`](../../ios/ZeldaRemoteCore) only implements protocol parsing, client transport, and UI-agnostic state.
