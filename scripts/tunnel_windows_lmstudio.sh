#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-medical-mechanica}"
LOCAL_PORT="${LOCAL_PORT:-2234}"
REMOTE_PORT="${REMOTE_PORT:-1234}"
BACKGROUND=0

usage() {
  cat <<'USAGE'
Usage: tunnel_windows_lmstudio.sh [--host HOST] [--local-port PORT] [--remote-port PORT] [--background]

Open an SSH tunnel from the local machine to LM Studio on the Windows host.
Default mapping: 127.0.0.1:2234 -> medical-mechanica:127.0.0.1:1234
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --local-port)
      LOCAL_PORT="$2"
      shift 2
      ;;
    --remote-port)
      REMOTE_PORT="$2"
      shift 2
      ;;
    --background)
      BACKGROUND=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

SSH_ARGS=(
  -o ExitOnForwardFailure=yes
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"
  "$HOST"
)

if [[ "$BACKGROUND" -eq 1 ]]; then
  exec ssh -f -N "${SSH_ARGS[@]}"
fi

exec ssh -N "${SSH_ARGS[@]}"
