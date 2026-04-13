"""LM Studio CLI helpers for z3cli."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def _find_lms() -> str:
    path = shutil.which("lms")
    if not path:
        raise RuntimeError("lms not found in PATH. Install LM Studio CLI first.")
    return path


def _json_from_output(output: str) -> Any:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("{") or line.startswith("["):
            return json.loads(line)
    raise ValueError("No JSON payload found in lms output")


def run_lms(args: list[str], host: str, port: int, instance: bool = True) -> str:
    command = [_find_lms(), *args]
    if instance:
        command.extend(["--host", host, "--port", str(port)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "lms command failed"
        raise RuntimeError(detail)
    return result.stdout


def server_status(host: str, port: int) -> dict[str, Any]:
    payload = _json_from_output(run_lms(["server", "status", "--json"], host, port, instance=False))
    return payload if isinstance(payload, dict) else {}


def ensure_server(host: str, port: int) -> None:
    status = server_status(host, port)
    if status.get("running"):
        return
    run_lms(["server", "start"], host, port, instance=False)


def available_models(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(run_lms(["ls", "--json"], host, port))
    return payload if isinstance(payload, list) else []


def loaded_models(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(run_lms(["ps", "--json"], host, port))
    return payload if isinstance(payload, list) else []


def loaded_request_name(alias: str, model_id: str, loaded: list[dict[str, Any]]) -> str | None:
    for entry in loaded:
        identifier = entry.get("identifier")
        if isinstance(identifier, str) and identifier == alias:
            return identifier
        for key in ("modelKey", "modelPath", "name", "model", "id"):
            value = entry.get(key)
            if isinstance(value, str) and value == model_id:
                return model_id
    return None


def ensure_model_loaded(
    alias: str,
    model_id: str,
    host: str,
    port: int,
    auto_load: bool,
    ttl: int | None = None,
) -> str:
    loaded = loaded_models(host, port)
    request_name = loaded_request_name(alias, model_id, loaded)
    if request_name:
        return request_name
    if not auto_load:
        raise RuntimeError(f"Model '{alias}' is not loaded in LM Studio. Use /load or start with --auto-load.")
    args = ["load", model_id, "--yes", "--identifier", alias]
    if ttl:
        args.extend(["--ttl", str(ttl)])
    run_lms(args, host, port)
    return alias
