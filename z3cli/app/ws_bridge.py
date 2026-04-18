"""WebSocket bridge: one NDJSON line per frame, proxied to `z3cli --serve` stdio.

Requires optional dependency: pip install 'z3cli[bridge]'

Use from Tailscale: bind --bridge-host to your tailnet IP or 0.0.0.0 and connect
from iOS with header ``Authorization: Bearer <token>`` on the WebSocket handshake.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

logger = logging.getLogger(__name__)

try:
    import websockets
except ImportError:  # pragma: no cover - exercised when extras missing
    websockets = None  # type: ignore[assignment]


def parse_bridge_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="z3cli --bridge",
        description="Expose z3cli --serve over WebSocket (one text frame = one NDJSON line).",
    )
    parser.add_argument(
        "--bridge-host",
        default=os.environ.get("Z3CLI_BRIDGE_HOST", "127.0.0.1"),
        help="Listen address (use 0.0.0.0 for Tailscale/LAN).",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=int(os.environ.get("Z3CLI_BRIDGE_PORT", "8765")),
        help="Listen port.",
    )
    parser.add_argument(
        "--bridge-token",
        default=os.environ.get("Z3CLI_BRIDGE_TOKEN", ""),
        help="Shared secret; client must send Authorization: Bearer <token>. "
        "Set via env Z3CLI_BRIDGE_TOKEN if preferred.",
    )
    parsed, serve_args = parser.parse_known_args(argv)
    return parsed, serve_args


def _auth_header_from_websocket(ws: Any) -> str:
    """Return Authorization header value (may be empty)."""
    req = getattr(ws, "request", None)
    if req is not None:
        headers = getattr(req, "headers", None)
        if headers is not None:
            h = headers.get("Authorization") or headers.get("authorization")
            if h:
                return str(h).strip()
    rh = getattr(ws, "request_headers", None)
    if rh is not None:
        h = rh.get("Authorization") or rh.get("authorization")
        if h:
            return str(h).strip()
    return ""


async def _drain_stderr(proc: asyncio.subprocess.Process) -> None:
    if proc.stderr is None:
        return
    try:
        while True:
            line_b = await proc.stderr.readline()
            if not line_b:
                break
            line = line_b.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.warning("serve stderr: %s", line)
    except Exception:
        logger.debug("bridge: stderr drain failed", exc_info=True)


async def _proxy_connection(
    websocket: Any,
    *,
    bridge_token: str,
    serve_args: list[str],
) -> None:
    expected = f"Bearer {bridge_token}"
    got = _auth_header_from_websocket(websocket)
    if got != expected:
        logger.warning("bridge: unauthorized connection attempt")
        await websocket.close(code=4001, reason="unauthorized")
        return

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "z3cli",
        "--serve",
        *serve_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )

    assert proc.stdin is not None and proc.stdout is not None

    stderr_task = asyncio.create_task(_drain_stderr(proc))

    async def pump_stdout_to_ws() -> None:
        try:
            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue
                await websocket.send(line)
        except Exception:
            logger.exception("bridge: pump_stdout_to_ws failed")
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    async def pump_ws_to_stdin() -> None:
        try:
            async for message in websocket:
                if isinstance(message, (bytes, bytearray)):
                    text = bytes(message).decode("utf-8", errors="replace")
                else:
                    text = str(message)
                if not text.endswith("\n"):
                    text = text + "\n"
                proc.stdin.write(text.encode("utf-8"))
                await proc.stdin.drain()
        except Exception:
            logger.debug("bridge: pump_ws_to_stdin ended", exc_info=True)
        finally:
            try:
                shutdown = (json.dumps({"jsonrpc": "2.0", "method": "shutdown"}) + "\n").encode(
                    "utf-8",
                )
                proc.stdin.write(shutdown)
                await proc.stdin.drain()
            except Exception:
                pass
            try:
                proc.stdin.close()
                await proc.stdin.wait_closed()
            except Exception:
                pass

    out_task = asyncio.create_task(pump_stdout_to_ws())
    in_task = asyncio.create_task(pump_ws_to_stdin())
    _done, pending = await asyncio.wait(
        {out_task, in_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    stderr_task.cancel()
    try:
        await stderr_task
    except asyncio.CancelledError:
        pass
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()
    except Exception:
        logger.exception("bridge: process cleanup")


async def bridge_main(argv: list[str]) -> None:
    if websockets is None:
        print(
            "The WebSocket bridge requires the 'bridge' extra: pip install 'z3cli[bridge]'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    parsed, serve_args = parse_bridge_args(argv)
    if not parsed.bridge_token.strip():
        print(
            "Refusing to start without --bridge-token or Z3CLI_BRIDGE_TOKEN.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def handler(websocket: Any, *_args: Any) -> None:
        await _proxy_connection(
            websocket,
            bridge_token=parsed.bridge_token.strip(),
            serve_args=serve_args,
        )

    host = parsed.bridge_host
    port = parsed.bridge_port
    logger.info("z3cli bridge listening on ws://%s:%s (serve args: %s)", host, port, serve_args)

    server = await websockets.serve(handler, host, port)  # type: ignore[attr-defined,misc]

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _stop() -> None:
        stop.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _stop)
        loop.add_signal_handler(signal.SIGTERM, _stop)
    except (NotImplementedError, AttributeError):
        pass

    await stop.wait()
    server.close()
    await server.wait_closed()


def run_bridge(argv: list[str] | None = None) -> None:
    """Entry for tests: parse argv and run bridge (blocks)."""
    if argv is None:
        argv = sys.argv[1:]
    asyncio.run(bridge_main(argv))
