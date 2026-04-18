#!/usr/bin/env bash
# Start the WebSocket bridge for iOS testing. Run from repo root or anywhere.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.bridge.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.bridge.env"
  set +a
fi

: "${Z3CLI_BRIDGE_TOKEN:?Set Z3CLI_BRIDGE_TOKEN (or put it in .bridge.env)}"
export Z3CLI_BRIDGE_HOST="${Z3CLI_BRIDGE_HOST:-0.0.0.0}"
export Z3CLI_BRIDGE_PORT="${Z3CLI_BRIDGE_PORT:-8765}"

TAIL_IP=""
if command -v tailscale >/dev/null 2>&1; then
  TAIL_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
fi

echo ""
echo "=== z3cli iOS bridge ==="
echo "Listening: ws://${Z3CLI_BRIDGE_HOST}:${Z3CLI_BRIDGE_PORT}"
if [[ -n "$TAIL_IP" ]]; then
  echo "On iPhone (Connect tab), try: ws://${TAIL_IP}:${Z3CLI_BRIDGE_PORT}"
else
  echo "On iPhone, use ws://<this-mac-tailscale-ipv4>:${Z3CLI_BRIDGE_PORT}  (install tailscale CLI or look up IP in the Tailscale app)"
fi
echo "Token: (same value you set in Z3CLI_BRIDGE_TOKEN)"
echo ""

SERVE_ARGS=()
if [[ -n "${Z3CLI_BRIDGE_SERVE_EXTRA:-}" ]]; then
  # shellcheck disable=SC2162
  read -r -a SERVE_ARGS <<< "${Z3CLI_BRIDGE_SERVE_EXTRA}"
fi

exec python3 -m z3cli --bridge \
  --bridge-host "$Z3CLI_BRIDGE_HOST" \
  --bridge-port "$Z3CLI_BRIDGE_PORT" \
  --bridge-token "$Z3CLI_BRIDGE_TOKEN" \
  -- "${SERVE_ARGS[@]}"
