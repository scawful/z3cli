# Protocol → Swift mapping

The canonical TypeScript definitions live in [`frontend/src/ipc/protocol.ts`](../../frontend/src/ipc/protocol.ts). The Swift implementation lives in [`ios/ZeldaRemoteCore`](../../ios/ZeldaRemoteCore).

## Wire format

- **Framing:** one JSON object per **line** (UTF-8, `\n` terminated), same as stdio serve mode.
- **WebSocket bridge:** one **text** WebSocket frame per line (see [`03-bridge.md`](./03-bridge.md)).
- **JSON-RPC:** requests include `"jsonrpc":"2.0"` and numeric `"id"`. Notifications have `"method"` and optional `"params"` and **no** `id`. Fire-and-forget client messages (e.g. `chat`, `cancel`) may be sent as notifications per existing Ink client ([`frontend/src/ipc/backend.ts`](../../frontend/src/ipc/backend.ts)).

## Methods (client → host)

| method | id | params (JSON keys) | Notes |
|--------|----|--------------------|-------|
| `chat` | omitted | `message`, optional `model` | Streaming via notifications |
| `command` | required | `cmd`, `args` (array) | Slash + `tool/decision` |
| `status` | required | — | Same payload shape as `ready` |
| `models` | required | — | Array of model dicts |
| `cancel` | — | — | Notification |
| `shutdown` | — | — | Notification |

## Notifications (host → client)

| method | params (snake_case in JSON) |
|--------|-----------------------------|
| `ready` | `version`, `backend`, `active_model`, `mode`, `workspace`, `rom_path`, `tools_enabled`, `servers`, `tool_count`, `warnings`, `models`, `session_path`, … |
| `text` | `delta` |
| `thinking` | `delta` |
| `tool_call` | `name`, `server`, `arguments` |
| `tool_result` | `name`, `result` |
| `message` | `id`, `role`, `content`, `timestamp`, optional `tool_*`, `attachments` |
| `done` | `prompt_tokens`, `completion_tokens`, `total_tokens` |
| `error` | `message` |
| `tool/permission_request` | `name`, `server`, `arguments` |

### Attachment metadata compatibility

`attachments` uses `AttachmentMeta`: `{ path, lines, chars }` in both
`message` and `chat` payloads.

For compatibility with older sessions or external clients, receivers should
default missing `lines` and `chars` to `0`.

## Tool permission commands

Same as Ink: `command` with `cmd: "tool/decision"`, `args: ["allow-once"]` | `["allow-session"]` | `["deny-once"]` | `["deny-session"]` (see [`useBackend.ts`](../../frontend/src/hooks/useBackend.ts)).

## Swift types

- **`IncomingLine` / `JSONLineParser`:** classifies each decoded JSON object as response vs notification.
- **`ZRMessage`, `ZRAppConfig`, `ZRModelInfo`:** app-level models (camelCase Swift properties, filled from snake_case dictionaries).
- **`BackendStore`:** ports the `useBackend` `switch (event.method)` behavior.
