#!/usr/bin/env python3
"""Run a JSONL prompt pack against an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PostFn = Callable[[str, dict[str, Any], float], dict[str, Any]]


def load_prompt_pack(path: Path) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            messages = row.get("messages")
            if not isinstance(messages, list):
                messages = []
                system = row.get("system")
                user = row.get("user")
                if isinstance(system, str) and system.strip():
                    messages.append({"role": "system", "content": system})
                if isinstance(user, str) and user.strip():
                    messages.append({"role": "user", "content": user})
            clean_messages = [
                {"role": str(message.get("role")), "content": str(message.get("content", ""))}
                for message in messages
                if isinstance(message, dict)
                and message.get("role") in {"system", "user", "assistant"}
                and str(message.get("content", "")).strip()
            ]
            if not clean_messages:
                raise ValueError(f"{path}:{line_number}: prompt row has no messages")
            row["_messages"] = clean_messages
            prompts.append(row)
    return prompts


def normalize_api_base(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base:
        raise ValueError("api base is required")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def post_chat_completion(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', 'EMPTY')}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return json.loads(raw)


def extract_completion(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    text = first.get("text")
    return text.strip() if isinstance(text, str) else ""


def build_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    top_p: float,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    if extra_body:
        payload.update(extra_body)
    return payload


def run_eval(
    *,
    prompt_pack: Path,
    out_path: Path,
    api_base: str,
    model: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    limit: int = 0,
    timeout: float = 300.0,
    retry_count: int = 1,
    retry_sleep: float = 2.0,
    extra_body: dict[str, Any] | None = None,
    post_fn: PostFn = post_chat_completion,
) -> int:
    prompts = load_prompt_pack(prompt_pack)
    if limit > 0:
        prompts = prompts[:limit]
    if not prompts:
        raise RuntimeError("No prompts found in prompt pack.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = normalize_api_base(api_base)
    run_meta = {
        "model": model,
        "api_base": api_base,
        "prompt_pack": str(prompt_pack),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with out_path.open("w", encoding="utf-8") as handle:
        for index, item in enumerate(prompts, start=1):
            messages = item["_messages"]
            payload = build_payload(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                extra_body=extra_body,
            )
            last_error = ""
            response: dict[str, Any] | None = None
            for attempt in range(max(1, retry_count + 1)):
                try:
                    response = post_fn(url, payload, timeout)
                    break
                except Exception as exc:  # noqa: BLE001 - preserve per-row failure in output.
                    last_error = str(exc)
                    if attempt < retry_count:
                        time.sleep(max(0.0, retry_sleep))
            completion = extract_completion(response or {})
            record = {
                "id": item.get("id"),
                "messages": messages,
                "completion": completion,
                "expected": item.get("response") or item.get("expected"),
                "tags": item.get("_metadata", {}).get("tags", []),
                "severity": item.get("_metadata", {}).get("severity"),
                "meta": {**run_meta, "index": index},
            }
            if last_error and response is None:
                record["error"] = last_error
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            handle.flush()
    return len(prompts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-pack", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument(
        "--extra-body-json",
        default="",
        help="Optional JSON object merged into each chat/completions payload.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    extra_body = json.loads(args.extra_body_json) if args.extra_body_json.strip() else None
    if extra_body is not None and not isinstance(extra_body, dict):
        raise TypeError("--extra-body-json must decode to an object")
    count = run_eval(
        prompt_pack=args.prompt_pack,
        out_path=args.out,
        api_base=args.api_base,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        limit=args.limit,
        timeout=args.timeout,
        retry_count=args.retry_count,
        retry_sleep=args.retry_sleep,
        extra_body=extra_body,
    )
    print(f"Wrote {count} completions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
