#!/usr/bin/env python3
"""Run and score the Oracle z3cli promotion gate.

This gate is intentionally different from the plain OpenAI-compatible prompt
pack runner: it observes real z3cli chat turns and scores tool calls emitted
through the z3cli runtime. It can launch ``z3cli --serve`` itself, or score an
existing z3cli session JSONL file when a live model is not available.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = (
    Path("/Users/scawful/src/training/evals")
    / "oracle_z3cli_promotion_holdout_v1.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "oracle-promotion-evals"
PREFETCH_CALL_ID_PREFIX = "oracle-prefetch-"


@dataclass
class ObservedResponse:
    """Observed z3cli behavior for one eval row."""

    id: str
    prompt: str
    request_id: str = ""
    session_path: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    thinking: str = ""
    end_status: str = ""
    errors: list[str] = field(default_factory=list)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row must be a JSON object")
            rows.append(row)
    return rows


def _prompt_from_row(row: dict[str, Any]) -> str:
    if isinstance(row.get("prompt"), str) and row["prompt"].strip():
        return row["prompt"].strip()
    if isinstance(row.get("user"), str) and row["user"].strip():
        return row["user"].strip()
    messages = row.get("messages")
    if isinstance(messages, list):
        users = [
            str(message.get("content", "")).strip()
            for message in messages
            if isinstance(message, dict)
            and message.get("role") == "user"
            and str(message.get("content", "")).strip()
        ]
        if users:
            return users[-1]
    raise ValueError(f"{row.get('id', '<unknown>')}: row has no user prompt")


def load_prompt_pack(path: Path) -> list[dict[str, Any]]:
    rows = _load_jsonl(path)
    if not rows:
        raise ValueError(f"{path}: no eval rows")
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            raise ValueError(f"{path}:{index}: row id is required")
        if row_id in seen:
            raise ValueError(f"{path}:{index}: duplicate row id {row_id!r}")
        seen.add(row_id)
        _prompt_from_row(row)
    return rows


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _parse_arguments(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value if value is not None else {}


def _args_text(arguments: Any) -> str:
    parsed = _parse_arguments(arguments)
    if isinstance(parsed, dict):
        text = json.dumps(parsed, sort_keys=True, ensure_ascii=False).lower()
    else:
        text = str(parsed or "").lower()
    # Let the gate treat common SNES register aliases as equivalent when the
    # model preserves the exact address instead of the mnemonic.
    compact = re.sub(r"[^0-9a-f]+", "", text)
    if "420b" in compact:
        text += " mdmaen"
    if "420c" in compact:
        text += " hdmaen"
    return text


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _expect_for(row: dict[str, Any]) -> dict[str, Any]:
    expect = row.get("expect")
    if isinstance(expect, dict):
        return expect
    out: dict[str, Any] = {}
    if row.get("expected_tool"):
        out["expected_tools_any"] = [row["expected_tool"]]
    if row.get("expected_args_contain"):
        out["expected_args_contain"] = row["expected_args_contain"]
    if row.get("tool_required") is not None:
        out["tool_required"] = bool(row["tool_required"])
    return out


def _check_patterns(text: str, patterns: list[str]) -> list[str]:
    failed: list[str] = []
    for pattern in patterns:
        try:
            matched = re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None
        except re.error:
            matched = pattern.lower() in text.lower()
        if not matched:
            failed.append(pattern)
    return failed


def score_response(row: dict[str, Any], observed: ObservedResponse) -> dict[str, Any]:
    expect = _expect_for(row)
    calls = observed.tool_calls
    call_names = [str(call.get("name") or "") for call in calls]
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: Any = None) -> None:
        entry: dict[str, Any] = {"name": name, "passed": bool(passed)}
        if detail not in (None, "", [], {}):
            entry["detail"] = detail
        checks.append(entry)

    end_status = observed.end_status or "unknown"
    add_check("request_succeeded", end_status in {"success", "unknown"}, end_status)

    if bool(expect.get("tool_required", False)):
        add_check("tool_required", bool(calls), call_names)

    expected_any = _as_str_list(expect.get("expected_tools_any"))
    if expected_any:
        add_check(
            "expected_tools_any",
            any(name in expected_any for name in call_names),
            {"expected": expected_any, "observed": call_names},
        )

    expected_all = _as_str_list(expect.get("expected_tools_all"))
    if expected_all:
        missing = [name for name in expected_all if name not in call_names]
        add_check("expected_tools_all", not missing, {"missing": missing, "observed": call_names})

    forbidden = set(_as_str_list(expect.get("forbidden_tools")))
    if forbidden:
        observed_forbidden = [name for name in call_names if name in forbidden]
        add_check("forbidden_tools", not observed_forbidden, observed_forbidden)

    if expect.get("min_tool_calls") is not None:
        minimum = int(expect["min_tool_calls"])
        add_check("min_tool_calls", len(calls) >= minimum, {"min": minimum, "observed": len(calls)})

    if expect.get("max_tool_calls") is not None:
        maximum = int(expect["max_tool_calls"])
        add_check("max_tool_calls", len(calls) <= maximum, {"max": maximum, "observed": len(calls)})

    expected_args = [token.lower() for token in _as_str_list(expect.get("expected_args_contain"))]
    if expected_args:
        arg_text = " | ".join(_args_text(call.get("arguments")) for call in calls)
        missing_args = [token for token in expected_args if token not in arg_text]
        add_check("expected_args_contain", not missing_args, {"missing": missing_args})

    if expect.get("max_reasoning_chars") is not None:
        maximum = int(expect["max_reasoning_chars"])
        thinking_len = len(observed.thinking or "")
        add_check("max_reasoning_chars", thinking_len <= maximum, {"max": maximum, "observed": thinking_len})

    require_any = _as_str_list(expect.get("require_final_contains_any"))
    if require_any:
        final_lower = observed.final_text.lower()
        add_check(
            "require_final_contains_any",
            any(token.lower() in final_lower for token in require_any),
            require_any,
        )

    require_patterns = _as_str_list(expect.get("require_final_patterns"))
    if require_patterns:
        missing_patterns = _check_patterns(observed.final_text, require_patterns)
        add_check("require_final_patterns", not missing_patterns, {"missing": missing_patterns})

    forbidden_patterns = _as_str_list(expect.get("forbid_final_patterns"))
    if forbidden_patterns:
        found = [pattern for pattern in forbidden_patterns if not _check_patterns(observed.final_text, [pattern])]
        add_check("forbid_final_patterns", not found, {"found": found})

    if observed.errors:
        add_check("no_runtime_errors", False, observed.errors)

    passed = all(check["passed"] for check in checks)
    return {
        "id": observed.id,
        "passed": passed,
        "checks": checks,
        "tool_calls_observed": call_names,
        "tool_call_count": len(calls),
        "request_id": observed.request_id,
        "end_status": observed.end_status,
        "final_text_preview": observed.final_text[:240],
    }


def _call_from_session(call: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(call, dict):
        return None
    function = call.get("function")
    if isinstance(function, dict):
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments", "{}")
    else:
        name = str(call.get("name") or "").strip()
        arguments = call.get("arguments", "{}")
    if not name:
        return None
    return {
        "name": name,
        "arguments": _parse_arguments(arguments),
        "server": str(call.get("server") or ""),
        "tool_call_id": str(call.get("tool_call_id") or call.get("id") or ""),
    }


def _load_session_engine_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("type") == "engine_msg":
            records.append(rec)
    return records


def _find_session_turn(
    records: list[dict[str, Any]],
    *,
    prompt: str,
    model: str = "",
) -> tuple[int, dict[str, Any]] | None:
    needle = _normalize_text(prompt)
    fallback_needle = needle[:80]
    for index, rec in enumerate(records):
        if model and rec.get("model") != model:
            continue
        msg = rec.get("msg") or {}
        if msg.get("role") != "user":
            continue
        display = _normalize_text(msg.get("display_content") or "")
        content = _normalize_text(msg.get("content") or "")
        if display == needle or content == needle:
            return index, rec
        if fallback_needle and (display.startswith(fallback_needle) or content.startswith(fallback_needle)):
            return index, rec
    return None


def collect_session_response(
    records: list[dict[str, Any]],
    *,
    row_id: str,
    prompt: str,
    model: str = "",
    session_path: str = "",
    include_prefetch: bool = False,
) -> ObservedResponse:
    found = _find_session_turn(records, prompt=prompt, model=model)
    observed = ObservedResponse(id=row_id, prompt=prompt, session_path=session_path)
    if found is None:
        observed.end_status = "missing"
        observed.errors.append("prompt not found in session")
        return observed

    start_index, start_rec = found
    start_msg = start_rec.get("msg") or {}
    turn_id = str(start_msg.get("turn_id") or "")
    request_id = str(start_msg.get("request_id") or "")
    observed.request_id = request_id

    for rec in records[start_index + 1 :]:
        if model and rec.get("model") != model:
            continue
        msg = rec.get("msg") or {}
        role = msg.get("role")
        same_turn = True
        if turn_id:
            same_turn = str(msg.get("turn_id") or "") == turn_id
        elif request_id:
            same_turn = str(msg.get("request_id") or "") == request_id
        elif role == "user":
            break
        if not same_turn:
            if role == "user":
                break
            continue
        if role == "user":
            break
        if role == "assistant":
            thinking = str(msg.get("thinking") or "")
            if thinking:
                observed.thinking += thinking
            content = str(msg.get("content") or "")
            if content:
                observed.final_text += content
            for call in msg.get("tool_calls") or []:
                parsed = _call_from_session(call)
                if parsed is None:
                    continue
                call_id = str(parsed.get("tool_call_id") or "")
                if not include_prefetch and call_id.startswith(PREFETCH_CALL_ID_PREFIX):
                    continue
                observed.tool_calls.append(parsed)
        elif role == "tool":
            call_id = str(msg.get("tool_call_id") or "")
            if not include_prefetch and call_id.startswith(PREFETCH_CALL_ID_PREFIX):
                continue
            observed.tool_results.append({
                "name": str(msg.get("name") or ""),
                "content": str(msg.get("content") or ""),
                "server": str(msg.get("server") or ""),
                "tool_call_id": call_id,
            })
    observed.end_status = "success"
    return observed


def score_session_file(
    *,
    rows: list[dict[str, Any]],
    session_path: Path,
    model: str = "",
    include_prefetch: bool = False,
) -> list[dict[str, Any]]:
    records = _load_session_engine_records(session_path)
    results: list[dict[str, Any]] = []
    for row in rows:
        observed = collect_session_response(
            records,
            row_id=str(row["id"]),
            prompt=_prompt_from_row(row),
            model=model,
            session_path=str(session_path),
            include_prefetch=include_prefetch,
        )
        result = score_response(row, observed)
        result["observed"] = {
            "prompt": observed.prompt,
            "session_path": observed.session_path,
            "tool_calls": observed.tool_calls,
            "tool_results": observed.tool_results,
            "final_text": observed.final_text,
            "thinking_chars": len(observed.thinking),
            "errors": observed.errors,
        }
        results.append(result)
    return results


class ServeClient:
    """Small NDJSON JSON-RPC client for ``z3cli --serve``."""

    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc
        self._next_id = 1
        self._pending_responses: dict[int, dict[str, Any]] = {}

    async def close(self) -> None:
        if self.proc.stdin and self.proc.returncode is None:
            await self.send_notification("shutdown", {})
            self.proc.stdin.close()
            with contextlib.suppress(Exception):  # type: ignore[name-defined]
                await self.proc.stdin.wait_closed()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()

    async def write(self, payload: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("serve stdin is unavailable")
        self.proc.stdin.write((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

    async def send_notification(self, method: str, params: dict[str, Any]) -> None:
        await self.write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        req_id = self._next_id
        self._next_id += 1
        await self.write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return req_id, await self.read_response(req_id)

    async def read_message(self, timeout: float) -> dict[str, Any]:
        if self.proc.stdout is None:
            raise RuntimeError("serve stdout is unavailable")
        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
        if not line:
            stderr = ""
            if self.proc.stderr is not None:
                with contextlib.suppress(Exception):  # type: ignore[name-defined]
                    stderr = (await self.proc.stderr.read()).decode("utf-8", errors="replace")
            raise RuntimeError(f"z3cli --serve exited before response. {stderr[:500]}")
        return json.loads(line.decode("utf-8"))

    async def read_response(self, req_id: int, timeout: float = 60.0) -> dict[str, Any]:
        if req_id in self._pending_responses:
            return self._pending_responses.pop(req_id)
        while True:
            msg = await self.read_message(timeout)
            if "id" in msg:
                msg_id = int(msg["id"])
                if msg_id == req_id:
                    return msg
                self._pending_responses[msg_id] = msg


async def _start_serve(args: argparse.Namespace, run_dir: Path) -> tuple[ServeClient, str]:
    env = os.environ.copy()
    session_dir = Path(args.session_dir).expanduser() if args.session_dir else run_dir / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    env["Z3CLI_SESSION_DIR"] = str(session_dir)
    env.setdefault("Z3CLI_DEFER_STARTUP_TOOL_BRIDGE", "0")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "z3cli.py"),
        "--serve",
        "--model",
        args.model,
        "--mode",
        args.mode,
        "--backend",
        args.backend,
        "--workspace",
        str(Path(args.workspace).expanduser()),
        "--auto-start-server" if args.auto_start_server else "--no-auto-start-server",
        "--auto-load" if args.auto_load else "--no-auto-load",
        "--tools" if args.tools else "--no-tools",
    ]
    if args.rom:
        cmd.extend(["--rom", str(Path(args.rom).expanduser())])
    if args.studio_api_base:
        cmd.extend(["--api-base", args.studio_api_base])
    if args.studio_node:
        cmd.extend(["--studio-node", args.studio_node])
    for extra in args.serve_arg or []:
        cmd.append(extra)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    client = ServeClient(proc)

    ready: dict[str, Any] | None = None
    deadline = asyncio.get_running_loop().time() + args.startup_timeout
    try:
        while asyncio.get_running_loop().time() < deadline:
            try:
                msg = await client.read_message(timeout=max(1.0, min(5.0, deadline - asyncio.get_running_loop().time())))
            except asyncio.TimeoutError:
                # Model auto-load and tool bridge warmup can legitimately take
                # longer than a single poll interval. Keep waiting until the
                # real startup deadline instead of failing at the first quiet
                # five-second window.
                if proc.returncode is not None:
                    break
                continue
            if msg.get("method") == "ready":
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                ready = params
                break
    except Exception:
        await client.close()
        raise
    if ready is None:
        await client.close()
        raise TimeoutError("z3cli --serve did not emit ready before startup timeout")
    return client, str(ready.get("session_path") or "")


async def run_live_eval(
    *,
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
    run_dir: Path,
) -> list[dict[str, Any]]:
    client, session_path = await _start_serve(args, run_dir)
    results: list[dict[str, Any]] = []
    try:
        for index, row in enumerate(rows):
            prompt = _prompt_from_row(row)
            observed = ObservedResponse(id=str(row["id"]), prompt=prompt, session_path=session_path)
            req_msg_id, accepted = await client.request(
                "chat",
                {"message": prompt, "model": args.model},
            )
            if accepted.get("error"):
                observed.errors.append(accepted["error"].get("message", "chat request rejected"))
                observed.end_status = "error"
                result = score_response(row, observed)
                result["observed"] = observed.__dict__
                results.append(result)
                continue
            request_id = str((accepted.get("result") or {}).get("request_id") or "")
            observed.request_id = request_id
            while True:
                msg = await client.read_message(timeout=args.row_timeout)
                method = str(msg.get("method") or "")
                params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                if "id" in msg and int(msg["id"]) == req_msg_id:
                    continue
                if request_id and params.get("request_id") not in {None, request_id}:
                    continue
                if method == "text":
                    observed.final_text += str(params.get("delta") or "")
                elif method == "thinking":
                    observed.thinking += str(params.get("delta") or "")
                elif method == "tool/permission_request":
                    if args.auto_approve_tools:
                        await client.request(
                            "command",
                            {"cmd": "tool/decision", "args": ["allow-once"]},
                        )
                    else:
                        observed.errors.append(
                            f"tool permission requested for {params.get('server', '')}:{params.get('name', '')}"
                        )
                elif method == "tool_call":
                    observed.tool_calls.append({
                        "name": str(params.get("name") or ""),
                        "arguments": _parse_arguments(params.get("arguments")),
                        "server": str(params.get("server") or ""),
                        "tool_call_id": str(params.get("call_id") or ""),
                    })
                elif method == "tool_result":
                    observed.tool_results.append({
                        "name": str(params.get("name") or ""),
                        "content": str(params.get("result") or ""),
                        "server": str(params.get("server") or ""),
                        "tool_call_id": str(params.get("call_id") or ""),
                    })
                elif method == "error":
                    observed.errors.append(str(params.get("message") or "unknown error"))
                elif method == "done":
                    observed.end_status = str(params.get("end_status") or "success")
                    break
            result = score_response(row, observed)
            result["observed"] = observed.__dict__
            results.append(result)
            if args.reset_between_rows and index < len(rows) - 1:
                await client.request("command", {"cmd": "reset", "args": ["all"]})
    finally:
        await client.close()
    return results


def summarize_results(results: list[dict[str, Any]], *, pack: Path, session_path: str = "") -> dict[str, Any]:
    passed = sum(1 for row in results if row.get("passed"))
    total = len(results)
    return {
        "summary": {
            "pack": str(pack),
            "rows_total": total,
            "rows_passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "session_path": session_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


def write_results(path: Path, results: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        handle.write(json.dumps(summary, ensure_ascii=True) + "\n")


async def async_main(args: argparse.Namespace) -> int:
    rows = load_prompt_pack(Path(args.prompt_pack).expanduser())
    if args.limit > 0:
        rows = rows[: args.limit]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = Path(args.out).expanduser() if args.out else DEFAULT_OUT_DIR / f"oracle_z3cli_promotion_{timestamp}.jsonl"
    run_dir = out.parent / f"{out.stem}_artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.session:
        session_path = Path(args.session).expanduser()
        results = score_session_file(
            rows=rows,
            session_path=session_path,
            model=args.model if args.model_filter else "",
            include_prefetch=args.include_prefetch,
        )
        summary = summarize_results(results, pack=Path(args.prompt_pack).expanduser(), session_path=str(session_path))
    else:
        results = await run_live_eval(rows=rows, args=args, run_dir=run_dir)
        session_path = ""
        for row in results:
            observed = row.get("observed") if isinstance(row.get("observed"), dict) else {}
            if observed.get("session_path"):
                session_path = str(observed["session_path"])
                break
        summary = summarize_results(results, pack=Path(args.prompt_pack).expanduser(), session_path=session_path)

    write_results(out, results, summary)
    print(json.dumps(summary, ensure_ascii=True))
    print(f"Wrote z3cli promotion eval results to {out}")
    return 0 if summary["summary"]["rows_passed"] == summary["summary"]["rows_total"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--session", type=Path, default=None, help="Score an existing z3cli session JSONL instead of launching z3cli --serve.")
    parser.add_argument("--include-prefetch", action="store_true", help="Count oracle-prefetch session records as observed tool calls when scoring --session.")
    parser.add_argument("--model", default="oracle-qwen35-9b")
    parser.add_argument("--model-filter", action="store_true", help="When scoring --session, only match turns for --model.")
    parser.add_argument("--mode", default="manual")
    parser.add_argument("--backend", default=os.environ.get("Z3CLI_BACKEND", "studio"))
    parser.add_argument("--workspace", default=str(REPO_ROOT))
    parser.add_argument("--rom", default="")
    parser.add_argument("--studio-api-base", default=os.environ.get("LMSTUDIO_BASE_URL", ""))
    parser.add_argument("--studio-node", default=os.environ.get("Z3CLI_STUDIO_NODE", ""))
    parser.add_argument("--session-dir", default="")
    parser.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-approve-tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--reset-between-rows",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reset z3cli model conversation state between live eval rows.",
    )
    parser.add_argument("--auto-load", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-start-server", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--row-timeout", type=float, default=300.0)
    parser.add_argument("--serve-arg", action="append", default=[], help="Additional single argument passed to z3cli --serve; repeat as needed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
