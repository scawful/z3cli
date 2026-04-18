# WebSocket bridge (Tailscale-first)

The Python backend for the Ink UI speaks **newline-delimited JSON-RPC** on **stdio** (`z3cli --serve`). iOS cannot attach to that directly, so this repo adds **`z3cli --bridge`**: a small process that accepts **WebSocket** connections and proxies **one text frame ↔ one NDJSON line** to a child `z3cli --serve` process.

Implementation: [`z3cli/app/ws_bridge.py`](../../z3cli/app/ws_bridge.py). Entry: [`z3cli/__main__.py`](../../z3cli/__main__.py) (`--bridge`).

## Install

```bash
pip install 'z3cli[bridge]'
```

## Run (example)

```bash
export Z3CLI_BRIDGE_TOKEN='choose-a-long-random-secret'
python -m z3cli --bridge --bridge-host 0.0.0.0 --bridge-port 8765 -- --workspace ~/src/hobby
```

Arguments after `--` are forwarded to `z3cli --serve` (same flags as the desktop Ink frontend).

Bind `--bridge-host` to your Tailscale IP or `0.0.0.0` to listen on all interfaces on the **tailnet** (still require the bearer token).

## Authentication

On the WebSocket **handshake**, the client must send:

```http
Authorization: Bearer <same value as --bridge-token or Z3CLI_BRIDGE_TOKEN>
```

Unauthorized clients receive close code **4001** (`unauthorized`).

## Framing rules

1. Each **outbound** WebSocket **text** message from the client must be exactly **one** JSON-RPC line (no embedded newlines), identical to what Ink writes to the serve process **stdin**.
2. Each **inbound** text message from the server is **one** line of stdout from serve (notifications, responses, etc.).
3. Binary frames are UTF-8 decoded when possible; avoid binary in clients.

## Semantics

- **One WebSocket session = one `z3cli --serve` child.** Disconnecting closes the session and terminates the child (after sending `shutdown` on stdin).
- **LM Studio / MCP** stay on the host; the phone only speaks JSON-RPC to the bridge.
- **Streaming**: `text`, `thinking`, `done`, etc. are forwarded as separate frames/lines — do not buffer until “full response” in intermediate proxies.

## Optional reverse proxy

If you later expose the bridge via `halext.org` or another HTTPS edge, terminate TLS at the proxy and use **WebSocket upgrade** with the same `Authorization` header. Ensure idle timeouts are compatible with long tool runs and permission prompts.
