"""LM Studio CLI helpers for z3cli.

Provides both sync and async entry points for invoking the `lms` CLI. Async
variants use ``asyncio.create_subprocess_exec`` so they never block the event
loop. Sync variants exist for startup paths that run before the loop and
always carry an explicit timeout so a hung ``lms`` cannot deadlock the REPL.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_LMS_TIMEOUT_S = 30.0
_MEMORY_ESTIMATE_RE = re.compile(
    r"Estimated\s+(GPU|Total)\s+Memory:\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B)",
    re.IGNORECASE,
)
_MEMORY_UNIT_FACTORS = {
    "b": 1,
    "kib": 1024,
    "mib": 1024 ** 2,
    "gib": 1024 ** 3,
    "tib": 1024 ** 4,
}


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


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _memory_amount_to_bytes(amount_text: str, unit_text: str) -> int:
    factor = _MEMORY_UNIT_FACTORS.get(unit_text.strip().lower(), 0)
    if factor <= 0:
        return 0
    try:
        return int(float(amount_text) * factor)
    except ValueError:
        return 0


def parse_estimated_memory_output(output: str) -> dict[str, int]:
    estimates: dict[str, int] = {}
    for line in output.splitlines():
        match = _MEMORY_ESTIMATE_RE.search(line)
        if match is None:
            continue
        kind, amount_text, unit_text = match.groups()
        size_bytes = _memory_amount_to_bytes(amount_text, unit_text)
        if size_bytes <= 0:
            continue
        if kind.lower() == "gpu":
            estimates["estimated_gpu_bytes"] = size_bytes
        else:
            estimates["estimated_total_bytes"] = size_bytes
    return estimates


def quantization_name(entry: dict[str, Any]) -> str:
    quant = entry.get("quantization")
    if isinstance(quant, dict):
        name = quant.get("name")
        if isinstance(name, str):
            return name
    value = entry.get("quantization")
    return value if isinstance(value, str) else ""


def loaded_model_lookup_keys(entry: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in (
        "identifier",
        "modelKey",
        "indexedModelIdentifier",
        "path",
        "displayName",
        "name",
        "model",
        "id",
    ):
        value = entry.get(key)
        if isinstance(value, str) and value and value not in keys:
            keys.append(value)
    return keys


def available_model_lookup(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in loaded_model_lookup_keys(entry):
            lookup.setdefault(key, entry)
    return lookup


def normalize_loaded_model_entry(
    entry: dict[str, Any],
    *,
    available_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lookup = available_lookup or {}
    keys = loaded_model_lookup_keys(entry)
    available_entry = next((lookup[key] for key in keys if key in lookup), None)
    model_key = _coerce_str(entry.get("modelKey")) or _coerce_str(entry.get("indexedModelIdentifier")) or _coerce_str(entry.get("id")) or _coerce_str(entry.get("path"))
    identifier = _coerce_str(entry.get("identifier")) or model_key or _coerce_str(entry.get("displayName"))
    display_name = _coerce_str(entry.get("displayName")) or _coerce_str(entry.get("name")) or identifier or model_key
    size_bytes = _coerce_int(entry.get("sizeBytes"))
    if size_bytes <= 0 and isinstance(available_entry, dict):
        size_bytes = _coerce_int(available_entry.get("sizeBytes"))
    architecture = _coerce_str(entry.get("architecture"))
    if not architecture and isinstance(available_entry, dict):
        architecture = _coerce_str(available_entry.get("architecture"))
    quantization = quantization_name(entry)
    if not quantization and isinstance(available_entry, dict):
        quantization = quantization_name(available_entry)
    context_length = _coerce_int(entry.get("contextLength"))
    max_context_length = _coerce_int(entry.get("maxContextLength"))
    if max_context_length <= 0 and isinstance(available_entry, dict):
        max_context_length = _coerce_int(available_entry.get("maxContextLength"))

    normalized: dict[str, Any] = {
        "identifier": identifier or model_key,
        "model_key": model_key or identifier,
    }
    if display_name:
        normalized["display_name"] = display_name
    if size_bytes > 0:
        normalized["size_bytes"] = size_bytes
    if architecture:
        normalized["architecture"] = architecture
    if quantization:
        normalized["quantization"] = quantization
    if context_length > 0:
        normalized["context_length"] = context_length
    if max_context_length > 0:
        normalized["max_context_length"] = max_context_length
    parallel = _coerce_int(entry.get("parallel"))
    if parallel > 0:
        normalized["parallel"] = parallel
    queued = _coerce_int(entry.get("queued"))
    if queued > 0:
        normalized["queued"] = queued
    status = _coerce_str(entry.get("status"))
    if status:
        normalized["status"] = status
    ttl_ms = _coerce_int(entry.get("ttlMs"))
    if ttl_ms > 0:
        normalized["ttl_ms"] = ttl_ms
    return normalized


def total_loaded_model_bytes(entries: Sequence[Mapping[str, Any]]) -> int:
    return sum(_coerce_int(entry.get("size_bytes")) for entry in entries)


def resolve_unload_target(target: str, loaded: list[dict[str, Any]]) -> str | None:
    wanted = target.strip()
    if not wanted:
        return None
    lower_wanted = wanted.lower()
    for entry in loaded:
        for key in loaded_model_lookup_keys(entry):
            if key.lower() == lower_wanted:
                identifier = _coerce_str(entry.get("identifier"))
                if identifier:
                    return identifier
                model_key = _coerce_str(entry.get("modelKey")) or _coerce_str(entry.get("id"))
                return model_key or key
    return None


def _build_command(args: list[str], host: str, port: int, instance: bool) -> list[str]:
    command = [_find_lms(), *args]
    if instance:
        command.extend(["--host", host, "--port", str(port)])
    return command


def run_lms(
    args: list[str],
    host: str,
    port: int,
    instance: bool = True,
    timeout: float = DEFAULT_LMS_TIMEOUT_S,
) -> str:
    """Run an ``lms`` subcommand synchronously with a bounded timeout."""
    command = _build_command(args, host, port, instance)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"lms command timed out after {timeout:.0f}s: {' '.join(args)}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "lms command failed"
        raise RuntimeError(detail)
    return result.stdout


async def run_lms_async(
    args: list[str],
    host: str,
    port: int,
    instance: bool = True,
    timeout: float = DEFAULT_LMS_TIMEOUT_S,
) -> str:
    """Run an ``lms`` subcommand under asyncio with a bounded timeout."""
    command = _build_command(args, host, port, instance)
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        raise RuntimeError(
            f"lms command timed out after {timeout:.0f}s: {' '.join(args)}"
        ) from exc
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "lms command failed"
        raise RuntimeError(detail)
    return stdout


def server_status(host: str, port: int) -> dict[str, Any]:
    payload = _json_from_output(run_lms(["server", "status", "--json"], host, port, instance=False))
    return payload if isinstance(payload, dict) else {}


async def server_status_async(host: str, port: int) -> dict[str, Any]:
    payload = _json_from_output(await run_lms_async(["server", "status", "--json"], host, port, instance=False))
    return payload if isinstance(payload, dict) else {}


def ensure_server(host: str, port: int) -> None:
    status = server_status(host, port)
    if status.get("running"):
        return
    run_lms(["server", "start"], host, port, instance=False)


async def ensure_server_async(host: str, port: int) -> None:
    status = await server_status_async(host, port)
    if status.get("running"):
        return
    await run_lms_async(["server", "start"], host, port, instance=False)


def available_models(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(run_lms(["ls", "--json"], host, port))
    return payload if isinstance(payload, list) else []


async def available_models_async(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(await run_lms_async(["ls", "--json"], host, port))
    return payload if isinstance(payload, list) else []


def loaded_models(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(run_lms(["ps", "--json"], host, port))
    return payload if isinstance(payload, list) else []


async def loaded_models_async(host: str, port: int) -> list[dict[str, Any]]:
    payload = _json_from_output(await run_lms_async(["ps", "--json"], host, port))
    return payload if isinstance(payload, list) else []


def unload_model(host: str, port: int, target: str = "", *, all_models: bool = False) -> dict[str, Any]:
    loaded = loaded_models(host, port)
    if all_models:
        if loaded:
            run_lms(["unload", "--all"], host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0))
        return {"all": True, "unloaded": [entry.get("identifier") or entry.get("modelKey") for entry in loaded]}
    resolved = resolve_unload_target(target, loaded)
    if not resolved:
        raise RuntimeError(f"Model '{target}' is not currently loaded in LM Studio.")
    run_lms(["unload", resolved], host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0))
    return {"all": False, "unloaded": [resolved]}


async def unload_model_async(host: str, port: int, target: str = "", *, all_models: bool = False) -> dict[str, Any]:
    loaded = await loaded_models_async(host, port)
    if all_models:
        if loaded:
            await run_lms_async(["unload", "--all"], host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0))
        return {"all": True, "unloaded": [entry.get("identifier") or entry.get("modelKey") for entry in loaded]}
    resolved = resolve_unload_target(target, loaded)
    if not resolved:
        raise RuntimeError(f"Model '{target}' is not currently loaded in LM Studio.")
    await run_lms_async(["unload", resolved], host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0))
    return {"all": False, "unloaded": [resolved]}


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


def _build_load_args(
    alias: str,
    model_id: str,
    context_length: int | None,
    parallel: int | None,
    gpu: str | None,
    ttl: int | None,
) -> list[str]:
    args = ["load", model_id, "--yes", "--identifier", alias]
    if context_length and context_length > 0:
        args.extend(["--context-length", str(context_length)])
    if parallel and parallel > 0:
        args.extend(["--parallel", str(parallel)])
    if gpu:
        args.extend(["--gpu", str(gpu)])
    if ttl:
        args.extend(["--ttl", str(ttl)])
    return args


def _build_estimate_args(
    model_id: str,
    *,
    context_length: int | None = None,
    gpu: str | None = None,
) -> list[str]:
    args = ["load", "--estimate-only", model_id]
    if context_length and context_length > 0:
        args.extend(["--context-length", str(context_length)])
    if gpu:
        args.extend(["--gpu", str(gpu)])
    return args


@lru_cache(maxsize=128)
def estimate_model_memory(
    host: str,
    port: int,
    model_id: str,
    *,
    context_length: int = 0,
    gpu: str = "",
) -> dict[str, int]:
    if not str(model_id or "").strip():
        return {}
    output = run_lms(
        _build_estimate_args(model_id, context_length=context_length or None, gpu=gpu or None),
        host,
        port,
        timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0),
    )
    return parse_estimated_memory_output(output)


async def estimate_model_memory_async(
    host: str,
    port: int,
    model_id: str,
    *,
    context_length: int = 0,
    gpu: str = "",
) -> dict[str, int]:
    if not str(model_id or "").strip():
        return {}
    output = await run_lms_async(
        _build_estimate_args(model_id, context_length=context_length or None, gpu=gpu or None),
        host,
        port,
        timeout=max(DEFAULT_LMS_TIMEOUT_S * 2, 60.0),
    )
    return parse_estimated_memory_output(output)


def ensure_model_loaded(
    alias: str,
    model_id: str,
    host: str,
    port: int,
    auto_load: bool,
    allow_auto_load: bool = True,
    manual_load: bool = False,
    context_length: int | None = None,
    parallel: int | None = None,
    gpu: str | None = None,
    ttl: int | None = None,
) -> str:
    loaded = loaded_models(host, port)
    request_name = loaded_request_name(alias, model_id, loaded)
    if request_name:
        return request_name
    if auto_load and not manual_load and not allow_auto_load:
        raise RuntimeError(
            f"Model '{alias}' is configured to skip automatic LM Studio loads. "
            f"Load it explicitly with /load {alias} if you want to opt in."
        )
    if not auto_load:
        raise RuntimeError(f"Model '{alias}' is not loaded in LM Studio. Use /load or start with --auto-load.")
    args = _build_load_args(alias, model_id, context_length, parallel, gpu, ttl)
    # Model loads can legitimately take minutes on larger checkpoints.
    run_lms(args, host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 10, 300.0))
    return alias


async def ensure_model_loaded_async(
    alias: str,
    model_id: str,
    host: str,
    port: int,
    auto_load: bool,
    allow_auto_load: bool = True,
    manual_load: bool = False,
    context_length: int | None = None,
    parallel: int | None = None,
    gpu: str | None = None,
    ttl: int | None = None,
) -> str:
    loaded = await loaded_models_async(host, port)
    request_name = loaded_request_name(alias, model_id, loaded)
    if request_name:
        return request_name
    if auto_load and not manual_load and not allow_auto_load:
        raise RuntimeError(
            f"Model '{alias}' is configured to skip automatic LM Studio loads. "
            f"Load it explicitly with /load {alias} if you want to opt in."
        )
    if not auto_load:
        raise RuntimeError(f"Model '{alias}' is not loaded in LM Studio. Use /load or start with --auto-load.")
    args = _build_load_args(alias, model_id, context_length, parallel, gpu, ttl)
    await run_lms_async(args, host, port, timeout=max(DEFAULT_LMS_TIMEOUT_S * 10, 300.0))
    return alias
