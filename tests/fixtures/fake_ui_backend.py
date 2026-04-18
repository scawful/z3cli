#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path


ATTACHMENT_RE = re.compile(r"(?<!\S)@([^\s@]+)")


def notify(method: str, params: dict | None = None) -> None:
    payload: dict[str, object] = {"jsonrpc": "2.0", "method": method}
    if params:
        payload["params"] = params
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def respond(req_id: int, result: object = None, error: str | None = None) -> None:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": req_id}
    if error:
        payload["error"] = {"code": -1, "message": error}
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def attachment_meta(workspace: Path, message: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in ATTACHMENT_RE.finditer(message):
        raw = (match.group(1) or "").rstrip(".,:;!?)]}")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        target = workspace / raw
        if not target.is_file():
            continue
        content = target.read_text(encoding="utf-8")
        items.append({
            "path": raw,
            "lines": content.count("\n") + 1,
            "chars": len(content),
        })
    return items


def normalize_attachments(
    workspace: Path,
    message: str,
    structured: object,
) -> list[dict[str, object]]:
    items = attachment_meta(workspace, message)
    seen = {str(item["path"]) for item in items}
    if not isinstance(structured, list):
        return items
    for entry in structured:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("path", "") or "").rstrip(".,:;!?)]}")
        if not raw or raw in seen:
            continue
        target = workspace / raw
        if not target.is_file():
            continue
        content = target.read_text(encoding="utf-8")
        items.append({
            "path": raw,
            "lines": content.count("\n") + 1,
            "chars": len(content),
        })
        seen.add(raw)
    return items


def visible_prompt(message: str) -> str:
    return "\n".join(
        line for line in message.splitlines()
        if not line.strip().startswith("@")
    ).strip() or "(attachment only)"


def main() -> int:
    workspace = Path(os.environ.get("Z3CLI_TEST_WORKSPACE", os.getcwd()))
    crash_on_command = str(os.environ.get("Z3CLI_TEST_CRASH_ON_COMMAND", "")).strip()
    crash_exit_code = int(str(os.environ.get("Z3CLI_TEST_CRASH_EXIT_CODE", "23")))
    crash_delay_s = max(0.0, float(str(os.environ.get("Z3CLI_TEST_CRASH_DELAY_MS", "0"))) / 1000.0)
    crash_after_ready_s = max(0.0, float(str(os.environ.get("Z3CLI_TEST_CRASH_AFTER_READY_MS", "0"))) / 1000.0)
    auto_permission = str(os.environ.get("Z3CLI_TEST_AUTO_PERMISSION", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    review_mode = str(os.environ.get("Z3CLI_TEST_REVIEW_MODE", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    auto_review = str(os.environ.get("Z3CLI_TEST_AUTO_REVIEW", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    turn_index = 0
    pending_review_id = ""
    waiting_for_review = False
    pending_permission_id = ""
    waiting_for_permission = False
    ready = {
        "version": "0.2.0-test",
        "backend": "studio",
        "active_model": "nayru",
        "studio_model": "nayru",
        "mode": "manual",
        "workspace": str(workspace),
        "rom_path": "",
        "tools_enabled": True,
        "tools_write": False,
        "servers": ["fake"],
        "tool_count": 1,
        "warnings": [],
        "models": [{
            "name": "nayru",
            "model_id": "nayru-model",
            "role": "analysis",
            "loaded": True,
            "tools_enabled": True,
            "context_budget": 8192,
        }],
        "session_path": str(workspace / "fake-session.jsonl"),
        "broadcast_models": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "session_messages": 0,
        "session_tool_calls": 0,
        "last_active_at": "2026-04-13T00:00:00+00:00",
        "last_active_model": "nayru",
        "permission_rules": {},
        "verify_hooks": True,
        "shell_active": False,
        "shell_cwd": str(workspace),
    }
    notify("ready", ready)
    if auto_review:
        pending_review_id = "review-auto-1"
        waiting_for_review = True
        notify("tool/review_request", {
            "review_id": pending_review_id,
            "name": "apply_patch",
            "server": "fake",
            "summary": "Pending write review",
            "paths": ["src/room.asm"],
            "diff_lines": [
                "--- src/room.asm",
                "+++ src/room.asm",
                "@@ -1,2 +1,2 @@",
                "-lda #$01",
                "+lda #$02",
            ],
            "omitted": 0,
            "verification_commands": ["python3 -m pytest -q tests/test_frontend_pty.py"],
        })

    if auto_permission:
        pending_permission_id = "permission-auto-1"
        waiting_for_permission = True
        notify("tool/permission_request", {
            "name": "write_file",
            "server": "fake",
            "arguments": '{"path": "src/room.asm", "content": "lda #$02\n"}',
            "reason": "Workspace policy requires explicit permission",
        })
    if crash_after_ready_s > 0:
        time.sleep(crash_after_ready_s)
        raise SystemExit(crash_exit_code)

    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        method = msg.get("method")
        params = msg.get("params", {}) or {}
        req_id = msg.get("id")

        if method == "command":
            cmd = str(params.get("cmd", ""))
            args = params.get("args", []) or []
            if crash_on_command and cmd == crash_on_command:
                if crash_delay_s > 0:
                    time.sleep(crash_delay_s)
                raise SystemExit(crash_exit_code)
            if cmd == "/status":
                respond(req_id, {
                    "backend": "studio",
                    "active_model": "nayru",
                    "workspace": str(workspace),
                    "mode": "manual",
                })
            elif cmd == "tool/review":
                review_id = str(args[0]) if len(args) > 0 else ""
                action = str(args[1]) if len(args) > 1 else ""
                if not pending_review_id or review_id != pending_review_id:
                    respond(req_id, error="No matching pending tool review")
                    continue
                waiting_for_review = False
                pending_review_id = ""
                respond(req_id, {"accepted": action == "accept"})
                notify("message", {
                    "id": f"review-{int(time.time() * 1000)}",
                    "role": "system",
                    "content": f"review decision: {action}",
                    "timestamp": int(time.time() * 1000),
                })
                notify("done", {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                })
            elif cmd == "tool/decision":
                if not waiting_for_permission:
                    respond(req_id, {"approved": False, "scope": "once"})
                    continue
                decision = str(args[0]) if args else ""
                waiting_for_permission = False
                pending_permission_id = ""
                notify("message", {
                    "id": f"permission-{int(time.time() * 1000)}",
                    "role": "system",
                    "content": f"permission decision: {decision}",
                    "timestamp": int(time.time() * 1000),
                })
                respond(req_id, {"approved": decision.startswith("allow"), "scope": str(args[0]) if args else "once"})
            elif cmd == "/shell":
                command = " ".join(str(arg) for arg in args).strip()
                respond(req_id, {
                    "cwd": str(workspace),
                    "exit_code": 0,
                    "duration_ms": 1,
                    "output": f"shell: {command}" if command else "",
                })
            elif cmd == "/verify-hooks":
                respond(req_id, {"verify_hooks": bool(args and args[0] == "on")})
            elif cmd == "/sessions":
                respond(req_id, {"sessions": []})
            else:
                respond(req_id, {"ok": True})
            continue

        if method == "chat":
            turn_index += 1
            prompt = str(params.get("message", ""))
            visible = visible_prompt(prompt)
            attachments = normalize_attachments(workspace, prompt, params.get("attachments"))
            construct_refs = [
                item for item in (params.get("construct_refs") or [])
                if isinstance(item, dict)
            ]
            timestamp = int(time.time() * 1000)
            notify("message", {
                "id": f"user-{turn_index}",
                "role": "user",
                "content": visible,
                "timestamp": timestamp,
                "turn_id": f"turn-{turn_index}",
                "attachments": attachments or None,
                "construct_refs": construct_refs or None,
            })
            notify("message", {
                "id": f"assistant-{turn_index}",
                "role": "assistant",
                "content": f"echo: {visible}",
                "timestamp": timestamp + 1,
                "turn_id": f"turn-{turn_index}",
                "model": "nayru",
            })
            if review_mode and "review" in visible.lower():
                pending_review_id = f"review-{turn_index}"
                waiting_for_review = True
                notify("tool/review_request", {
                    "review_id": pending_review_id,
                    "name": "apply_patch",
                    "server": "fake",
                    "summary": "Pending write review",
                    "paths": ["src/room.asm"],
                    "diff_lines": [
                        "--- src/room.asm",
                        "+++ src/room.asm",
                        "@@ -1,2 +1,2 @@",
                        "-lda #$01",
                        "+lda #$02",
                    ],
                    "omitted": 0,
                    "verification_commands": ["python3 -m pytest -q tests/test_frontend_pty.py"],
                })
                continue
            notify("done", {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            })
            continue

        if method == "cancel":
            if waiting_for_review:
                waiting_for_review = False
                pending_review_id = ""
            if waiting_for_permission:
                waiting_for_permission = False
                pending_permission_id = ""
            notify("done", {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            })
            continue

        if method == "shutdown":
            break

        if isinstance(req_id, int):
            respond(req_id, {"ok": True})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
