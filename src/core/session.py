"""Session persistence for z3cli.

Stores conversation history as append-only JSONL files with per-model
engine message tracking, resumable runtime state, and compact support.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOG = logging.getLogger(__name__)

DEFAULT_SESSION_DIR = Path.home() / ".local/share/z3cli/sessions"
_RECORD_META_KEYS = {"type", "ts"}


def default_session_dir() -> Path:
    """Resolve the writable session directory at runtime."""
    override = os.environ.get("Z3CLI_SESSION_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "z3cli" / "sessions"
    return DEFAULT_SESSION_DIR


def _counts_as_message(msg: dict[str, Any]) -> bool:
    role = msg.get("role")
    if role == "user":
        return True
    if role != "assistant":
        return False
    return bool(
        str(msg.get("content", "") or "").strip()
        or str(msg.get("thinking", "") or "").strip()
    )


@dataclass
class LoadedSession:
    """Parsed session data used to restore runtime state and UI transcript."""

    meta: dict[str, Any]
    model_messages: dict[str, list[dict[str, Any]]]
    transcript: list[dict[str, Any]]
    subagents: list[dict[str, Any]]
    message_count: int


def _slug(text: str, max_words: int = 4) -> str:
    """Generate a short slug from the first few words of text."""
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()[:max_words]
    return "-".join(words) if words else "session"


class Session:
    """Append-only JSONL session file."""

    def __init__(self, session_dir: Path | None = None):
        self._dir = session_dir or default_session_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path: Path | None = None
        self._handle = None
        self._msg_count = 0
        self._started = False
        self._closed = False
        # Tracks whether we've surfaced a write-dropped warning yet so we
        # log it at most once per session.
        self._degraded = False
        self._warned_not_started = False

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def message_count(self) -> int:
        return self._msg_count

    @property
    def degraded(self) -> bool:
        """True if writes are being dropped (session closed early or never started)."""
        return self._degraded

    def start(
        self,
        active_model: str,
        backend: str,
        mode: str,
        workspace: str,
        rom_path: str,
        tools_enabled: bool,
        broadcast_models: list[str],
        studio_api_base: str = "",
        studio_node: str = "",
        llamacpp_model: str = "",
        llamacpp_api_base: str = "",
        llamacpp_node: str = "",
        tools_write: bool = False,
        verify_hooks: bool = True,
        focus_path: str = "",
    ) -> None:
        """Create a new session file and write the meta record."""
        ts = datetime.now(timezone.utc)
        name = ts.strftime("%Y-%m-%d_%H%M%S_%f")
        self._path = self._dir / f"{name}.jsonl"
        counter = 1
        while self._path.exists():
            self._path = self._dir / f"{name}_{counter}.jsonl"
            counter += 1
        self._msg_count = 0
        self._started = True
        self._closed = False
        self._degraded = False
        self._handle = self._path.open("a", encoding="utf-8")
        self._write({
            "type": "meta",
            "active_model": active_model,
            "backend": backend,
            "mode": mode,
            "workspace": workspace,
            "rom_path": rom_path,
            "tools_enabled": tools_enabled,
            "tools_write": tools_write,
            "broadcast_models": broadcast_models,
            "studio_api_base": studio_api_base,
            "studio_node": studio_node,
            "llamacpp_model": llamacpp_model,
            "llamacpp_api_base": llamacpp_api_base,
            "llamacpp_node": llamacpp_node,
            "focus_path": focus_path,
            "verify_hooks": verify_hooks,
            "started": ts.isoformat(),
        })

    def append_engine_msg(self, model: str, msg: dict) -> None:
        """Append an engine message record tagged with the model name."""
        self._write({"type": "engine_msg", "model": model, "msg": msg})
        if _counts_as_message(msg):
            self._msg_count += 1

    def append_model_switch(self, from_model: str, to_model: str, reason: str = "") -> None:
        self._write({
            "type": "model_switch",
            "from": from_model,
            "to": to_model,
            "reason": reason,
        })

    def append_backend_switch(self, from_backend: str, to_backend: str) -> None:
        self._write({
            "type": "backend_switch",
            "from": from_backend,
            "to": to_backend,
        })

    def append_state_update(self, changes: dict[str, Any]) -> None:
        """Append a partial runtime-state update for resume fidelity."""
        if not changes:
            return
        self._write({
            "type": "state_update",
            "changes": changes,
        })

    def append_subagent_event(self, kind: str, payload: dict[str, Any]) -> None:
        """Append a subagent lifecycle event for resume/restoration."""
        self._write({
            "type": "subagent_event",
            "kind": kind,
            **payload,
        })

    def save_compact(self, model: str, summary: str, replaced_count: int) -> None:
        self._write({
            "type": "compact",
            "model": model,
            "summary": summary,
            "replaced_count": replaced_count,
        })

    def append_tool_invocation(
        self,
        tool: str,
        server: str,
        duration_ms: float,
        status: str,
        model: str = "",
        call_id: str = "",
        error: str = "",
    ) -> None:
        """Record a single bridge.call_tool invocation with timing + outcome.

        status is one of: success, timeout, cancelled, error, denied.
        """
        self._write({
            "type": "tool_invocation",
            "tool": tool,
            "server": server,
            "model": model,
            "call_id": call_id,
            "duration_ms": round(float(duration_ms), 2),
            "status": status,
            "error": error,
        })

    def rename_from_first_message(self, text: str) -> None:
        """Rename the session file based on the first user message."""
        if self._path is None:
            return
        slug = _slug(text)
        stem = self._path.stem
        new_name = f"{stem}_{slug}.jsonl"
        new_path = self._path.parent / new_name
        if new_path.exists() or new_path == self._path:
            return
        if self._handle:
            self._handle.close()
        self._path.rename(new_path)
        self._path = new_path
        self._handle = self._path.open("a", encoding="utf-8")

    def resume(self, path: Path, message_count: int) -> None:
        """Attach persistence to an existing session file."""
        path = path.expanduser().resolve()
        stale_path = self._path
        stale_count = self._msg_count
        self.close()
        if (
            stale_path
            and stale_path != path
            and stale_count == 0
            and stale_path.exists()
        ):
            try:
                stale_path.unlink()
            except OSError:
                pass
        self._path = path
        self._msg_count = message_count
        self._started = True
        self._closed = False
        self._degraded = False
        self._handle = self._path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._handle:
            self._handle.close()
            self._handle = None
        self._closed = True

    def _write(self, record: dict) -> None:
        if self._handle is None:
            # Silent for legitimate post-close writes or sessions that
            # haven't been started yet; warn once to surface bugs where a
            # caller forgot to call start().
            if not self._started and not self._warned_not_started:
                self._warned_not_started = True
                self._degraded = True
                _LOG.warning(
                    "Session._write called before start(); dropping %s record.",
                    record.get("type", "?"),
                )
            return
        record["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()
        except OSError as exc:
            if not self._degraded:
                self._degraded = True
                _LOG.warning("Session write failed for %s: %s", record.get("type", "?"), exc)


# ---------------------------------------------------------------------------
# Loading / listing
# ---------------------------------------------------------------------------

def _apply_state_record(state: dict[str, Any], rec: dict[str, Any]) -> None:
    rtype = rec.get("type")
    if rtype == "meta":
        for key, value in rec.items():
            if key not in _RECORD_META_KEYS:
                state[key] = value
        return
    if rtype == "model_switch":
        if rec.get("to"):
            state["active_model"] = rec["to"]
        return
    if rtype == "backend_switch":
        if rec.get("to"):
            state["backend"] = rec["to"]
        return
    if rtype == "state_update":
        changes = rec.get("changes")
        if isinstance(changes, dict):
            for key, value in changes.items():
                state[key] = value


def _timestamp_ms(value: Any, fallback: int) -> int:
    if isinstance(value, str) and value:
        try:
            return int(datetime.fromisoformat(value).timestamp() * 1000)
        except ValueError:
            pass
    return fallback


def _preview_text(value: str, max_chars: int = 96) -> str:
    text = " ".join(value.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _engine_message_view(msg: dict[str, Any]) -> dict[str, Any]:
    """Strip session-only metadata before restoring engine history."""
    role = str(msg.get("role", ""))
    cleaned: dict[str, Any] = {"role": role}

    if role in {"system", "user", "assistant"}:
        cleaned["content"] = msg.get("content", "")
    if role == "assistant" and isinstance(msg.get("tool_calls"), list):
        cleaned["tool_calls"] = msg["tool_calls"]
    if role == "tool":
        cleaned["content"] = msg.get("content", "")
        if msg.get("tool_call_id"):
            cleaned["tool_call_id"] = msg["tool_call_id"]

    return cleaned


def _normalize_tool_call_history(
    msgs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Restore provider-safe tool history from session-log engine messages.

    Session logs record tool calls in a z3cli-specific shape optimized for the
    transcript (`name`, `arguments`, `server`, `tool_call_id`, ...). Engines and
    OpenAI-compatible backends expect assistant `tool_calls` to use the
    OpenAI schema with `id`/`type`/`function`, and tool results must point back
    to one of those ids. Resume normalizes that structure and synthesizes ids
    for older sessions that did not record `tool_call_id`.
    """

    normalized: list[dict[str, Any]] = []
    pending_tool_ids: list[str] = []
    synthetic_index = 1

    for msg in msgs:
        cleaned = _engine_message_view(msg)
        role = str(cleaned.get("role", ""))

        if role == "assistant":
            raw_calls = cleaned.get("tool_calls")
            if isinstance(raw_calls, list):
                normalized_calls: list[dict[str, Any]] = []
                for call in raw_calls:
                    if not isinstance(call, dict):
                        continue

                    function = call.get("function")
                    if isinstance(function, dict):
                        call_id = str(
                            call.get("id")
                            or call.get("tool_call_id")
                            or f"restored_call_{synthetic_index}"
                        )
                        name = str(function.get("name", "") or "")
                        arguments = function.get("arguments", "{}")
                        call_type = str(call.get("type", "function") or "function")
                    else:
                        call_id = str(
                            call.get("tool_call_id")
                            or call.get("id")
                            or f"restored_call_{synthetic_index}"
                        )
                        name = str(call.get("name", "") or "")
                        arguments = call.get("arguments", "{}")
                        call_type = str(call.get("type", "function") or "function")

                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False)

                    normalized_calls.append({
                        "id": call_id,
                        "type": call_type,
                        "function": {
                            "name": name,
                            "arguments": arguments,
                        },
                    })
                    pending_tool_ids.append(call_id)
                    synthetic_index += 1

                if normalized_calls:
                    cleaned["tool_calls"] = normalized_calls
                else:
                    cleaned.pop("tool_calls", None)

        elif role == "tool":
            tool_call_id = str(cleaned.get("tool_call_id", "") or "").strip()
            if tool_call_id:
                if pending_tool_ids and pending_tool_ids[0] == tool_call_id:
                    pending_tool_ids.pop(0)
            elif pending_tool_ids:
                tool_call_id = pending_tool_ids.pop(0)
                cleaned["tool_call_id"] = tool_call_id

        normalized.append(cleaned)

    return normalized


def _training_message_view(
    msg: dict[str, Any],
    *,
    include_thinking: bool,
) -> dict[str, Any]:
    cleaned = dict(msg)
    if not include_thinking:
        cleaned.pop("thinking", None)
    return cleaned


def _build_transcript(
    records: list[dict[str, Any]],
    compact_points: dict[str, tuple[str, int]],
    *,
    include_thinking: bool,
) -> list[dict[str, Any]]:
    """Build a UI-friendly transcript from session records."""
    transcript: list[dict[str, Any]] = []
    last_compact_idx = {model: idx for model, (_summary, idx) in compact_points.items()}
    turn_index = 0
    current_turn_id = ""
    pending_tool_groups: list[str] = []
    transcript_index = 0

    for rec in records:
        rtype = rec.get("type")
        idx = int(rec.get("_idx", 0))
        timestamp = _timestamp_ms(rec.get("ts"), idx)

        if rtype == "engine_msg":
            model = str(rec.get("model", "unknown"))
            if model in last_compact_idx and idx <= last_compact_idx[model]:
                continue

            msg = rec.get("msg", {})
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")

            if role == "user":
                content = str(msg.get("display_content", msg.get("content", "")))
                if (
                    transcript
                    and transcript[-1].get("role") == "user"
                    and transcript[-1].get("content") == content
                ):
                    continue
                turn_index += 1
                current_turn_id = str(msg.get("turn_id") or f"turn-{turn_index}")
                transcript.append({
                    "id": f"msg-{transcript_index}",
                    "role": "user",
                    "content": content,
                    "timestamp": timestamp,
                    "turnId": current_turn_id,
                    "attachments": msg.get("attachments", []),
                    "constructRefs": msg.get("construct_refs", []),
                    "requestId": str(msg.get("request_id", "") or "") or None,
                })
                transcript_index += 1
                continue

            if role == "assistant":
                content = str(msg.get("content", "") or "")
                thinking = str(msg.get("thinking", "") or "")
                turn_id = str(msg.get("turn_id") or current_turn_id or f"turn-{max(turn_index, 1)}")
                if content.strip() or thinking.strip():
                    transcript.append({
                        "id": f"msg-{transcript_index}",
                        "role": "assistant",
                        "content": content,
                        "thinking": (thinking or None) if include_thinking else None,
                        "model": model,
                        "timestamp": timestamp,
                        "turnId": turn_id,
                        "requestId": str(msg.get("request_id", "") or "") or None,
                        "spanId": str(msg.get("span_id", "") or "") or None,
                    })
                    transcript_index += 1
                tool_calls = msg.get("tool_calls", [])
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        arguments = call.get("arguments", "")
                        if not isinstance(arguments, str):
                            arguments = json.dumps(arguments, ensure_ascii=False)
                        tool_group = str(
                            call.get("tool_group")
                            or call.get("tool_call_id")
                            or call.get("id")
                            or f"{turn_id}:tool-{len(pending_tool_groups) + 1}"
                        )
                        pending_tool_groups.append(tool_group)
                        transcript.append({
                            "id": f"msg-{transcript_index}",
                            "role": "tool",
                            "content": "",
                            "toolName": str(call.get("name", "tool")),
                            "toolServer": str(call.get("server", "")),
                            "toolArguments": arguments,
                            "timestamp": timestamp,
                            "turnId": turn_id,
                            "toolGroup": tool_group,
                            "model": model,
                            "requestId": str(call.get("request_id", msg.get("request_id", "")) or "") or None,
                            "spanId": str(call.get("span_id", msg.get("span_id", "")) or "") or None,
                        })
                        transcript_index += 1
                continue

            if role == "tool":
                turn_id = str(msg.get("turn_id") or current_turn_id or f"turn-{max(turn_index, 1)}")
                tool_group = str(msg.get("tool_group") or msg.get("tool_call_id") or "")
                if not tool_group:
                    tool_group = pending_tool_groups.pop(0) if pending_tool_groups else f"{turn_id}:tool-result-{transcript_index}"
                transcript.append({
                    "id": f"msg-{transcript_index}",
                    "role": "tool",
                    "content": str(msg.get("content", "")),
                    "toolName": str(msg.get("name", "tool")),
                    "toolServer": str(msg.get("server", "")),
                    "timestamp": timestamp,
                    "turnId": turn_id,
                    "toolGroup": tool_group,
                    "model": model,
                    "requestId": str(msg.get("request_id", "") or "") or None,
                    "spanId": str(msg.get("span_id", "") or "") or None,
                })
                transcript_index += 1
                continue

        if rtype == "compact":
            model = str(rec.get("model", "unknown"))
            if last_compact_idx.get(model) != idx:
                continue
            summary = str(rec.get("summary", "") or "").strip()
            content = f"Compacted **{model}** history."
            if summary:
                content += f"\n\n{summary}"
            transcript.append({
                "id": f"msg-{transcript_index}",
                "role": "system",
                "content": content,
                "timestamp": timestamp,
            })
            transcript_index += 1
            continue

        if rtype == "model_switch":
            transcript.append({
                "id": f"msg-{transcript_index}",
                "role": "system",
                "content": f"Switched model: `{rec.get('from', '?')}` → `{rec.get('to', '?')}`",
                "timestamp": timestamp,
            })
            transcript_index += 1
            continue

        if rtype == "backend_switch":
            transcript.append({
                "id": f"msg-{transcript_index}",
                "role": "system",
                "content": f"Switched backend: `{rec.get('from', '?')}` → `{rec.get('to', '?')}`",
                "timestamp": timestamp,
            })
            transcript_index += 1

    return transcript


def _build_subagent_entries(
    records: list[dict[str, Any]],
    fallback_finished_at: int,
    *,
    include_thinking: bool,
) -> list[dict[str, Any]]:
    """Rebuild final subagent panel state from recorded lifecycle events."""
    entries: list[dict[str, Any]] = []
    by_id: dict[str, int] = {}
    last_timestamp = fallback_finished_at

    for rec in records:
        kind = str(rec.get("kind", ""))
        subagent_id = str(rec.get("id", "") or "")
        timestamp = int(rec.get("timestamp", fallback_finished_at) or fallback_finished_at)
        last_timestamp = max(last_timestamp, timestamp)
        if not subagent_id:
            continue

        if kind == "start":
            entry = {
                "id": subagent_id,
                "name": str(rec.get("name", "")),
                "model": str(rec.get("model", "")),
                "provider": str(rec.get("provider", "")),
                "depth": int(rec.get("depth", 0) or 0),
                "status": "running",
                "text": "",
                "thinking": "" if include_thinking else "",
                "toolCallCount": 0,
                "startedAt": timestamp,
            }
            parent_id = str(rec.get("parent_id", "") or "")
            if parent_id:
                entry["parentId"] = parent_id
            existing = by_id.get(subagent_id)
            if existing is None:
                by_id[subagent_id] = len(entries)
                entries.append(entry)
            else:
                entries[existing] = entry
            continue

        pos = by_id.get(subagent_id)
        if pos is None:
            continue
        entry = entries[pos]

        if kind == "text":
            entry["text"] = str(entry.get("text", "")) + str(rec.get("delta", ""))
            continue

        if kind == "thinking":
            if include_thinking:
                entry["thinking"] = str(entry.get("thinking", "")) + str(rec.get("delta", ""))
            continue

        if kind == "tool_call":
            entry["toolCallCount"] = int(entry.get("toolCallCount", 0) or 0) + 1
            entry["activeTool"] = {
                "name": str(rec.get("name", "")),
                "server": str(rec.get("server", "")),
            }
            continue

        if kind == "tool_result":
            entry.pop("activeTool", None)
            continue

        if kind == "done":
            status = "done"
            if rec.get("cancelled"):
                status = "cancelled"
            if rec.get("error"):
                status = "error"
            entry["status"] = status
            text = str(rec.get("text", "") or "")
            if text:
                entry["text"] = text
            entry["toolCallCount"] = int(rec.get("tool_calls", entry.get("toolCallCount", 0)) or 0)
            entry["promptTokens"] = int(rec.get("prompt_tokens", 0) or 0)
            entry["completionTokens"] = int(rec.get("completion_tokens", 0) or 0)
            if rec.get("error"):
                entry["error"] = str(rec.get("error", ""))
            else:
                entry.pop("error", None)
            entry.pop("activeTool", None)
            entry["finishedAt"] = timestamp
            continue

        if kind == "error":
            entry["status"] = "error"
            entry["error"] = str(rec.get("message", ""))
            entry.pop("activeTool", None)
            entry["finishedAt"] = timestamp

    for entry in entries:
        if entry.get("status") == "running":
            entry["status"] = "cancelled"
            entry.pop("activeTool", None)
            entry["finishedAt"] = last_timestamp or int(entry.get("startedAt", 0) or 0)

    return entries
def _load_session_bundle(path: Path, *, include_thinking: bool) -> LoadedSession:
    meta: dict[str, Any] = {}
    all_msgs: dict[str, list[dict[str, Any]]] = {}
    compact_points: dict[str, tuple[str, int]] = {}
    transcript_records: list[dict[str, Any]] = []
    subagent_records: list[dict[str, Any]] = []
    message_count = 0
    tool_call_count = 0
    subagent_count = 0
    last_ts = ""
    last_preview = ""
    record_idx = 0

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = rec.get("type")
            _apply_state_record(meta, rec)
            ts_value = rec.get("ts")
            if isinstance(ts_value, str) and ts_value:
                last_ts = ts_value

            if rtype == "engine_msg":
                model = str(rec.get("model", "unknown"))
                msg = rec.get("msg", {})
                if not isinstance(msg, dict):
                    record_idx += 1
                    continue
                all_msgs.setdefault(model, []).append({"_idx": record_idx, **msg})
                transcript_records.append({
                    "type": "engine_msg",
                    "_idx": record_idx,
                    "ts": rec.get("ts"),
                    "model": model,
                    "msg": msg,
                })
                if _counts_as_message(msg):
                    message_count += 1
                    content = str(
                        msg.get("display_content", msg.get("content", "")) or "",
                    ).strip()
                    if content:
                        last_preview = _preview_text(content)
                tool_calls = msg.get("tool_calls", [])
                if isinstance(tool_calls, list):
                    tool_call_count += len(tool_calls)
            elif rtype == "compact":
                model = str(rec.get("model", "unknown"))
                compact_points[model] = (str(rec.get("summary", "")), record_idx)
                transcript_records.append({
                    "type": "compact",
                    "_idx": record_idx,
                    "ts": rec.get("ts"),
                    "model": model,
                    "summary": rec.get("summary", ""),
                })
                summary = str(rec.get("summary", "") or "").strip()
                if summary:
                    last_preview = _preview_text(summary)
            elif rtype == "subagent_event":
                kind = str(rec.get("kind", "") or "")
                if kind:
                    subagent_records.append({
                        "kind": kind,
                        "timestamp": _timestamp_ms(rec.get("ts"), record_idx),
                        **{
                            key: value
                            for key, value in rec.items()
                            if key not in _RECORD_META_KEYS and key not in {"type", "kind"}
                        },
                    })
                    if kind == "start":
                        subagent_count += 1
            elif rtype in {"model_switch", "backend_switch"}:
                transcript_records.append({
                    "type": rtype,
                    "_idx": record_idx,
                    "ts": rec.get("ts"),
                    "from": rec.get("from", ""),
                    "to": rec.get("to", ""),
                })

            record_idx += 1

    model_messages: dict[str, list[dict[str, Any]]] = {}
    for model, msgs in all_msgs.items():
        if model in compact_points:
            summary, compact_idx = compact_points[model]
            msgs = [msg for msg in msgs if msg.get("_idx", 0) > compact_idx]
            msgs.insert(0, {"role": "assistant", "content": summary})
        model_messages[model] = _normalize_tool_call_history([
            {k: v for k, v in msg.items() if k != "_idx"}
            for msg in msgs
        ])

    meta.setdefault("prompt_tokens", 0)
    meta.setdefault("completion_tokens", 0)
    meta.setdefault("tool_call_count", tool_call_count)
    meta.setdefault("subagent_count", subagent_count)
    meta.setdefault("message_count", message_count)
    meta.setdefault("permission_rules", {})
    if last_ts:
        meta.setdefault("last_active_at", last_ts)
    if last_preview:
        meta.setdefault("preview", last_preview)

    return LoadedSession(
        meta=meta,
        model_messages=model_messages,
        transcript=_build_transcript(
            transcript_records,
            compact_points,
            include_thinking=include_thinking,
        ),
        subagents=_build_subagent_entries(
            subagent_records,
            _timestamp_ms(last_ts, record_idx),
            include_thinking=include_thinking,
        ),
        message_count=message_count,
    )


def find_session(name: str, session_dir: Path | None = None) -> dict[str, Any]:
    """Resolve a session name with exact-match preference and ambiguity checks."""
    sessions = list_sessions(session_dir)
    exact = [session for session in sessions if session["name"] == name]
    if exact:
        return exact[0]

    partial = [session for session in sessions if name in session["name"]]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(session["name"] for session in partial[:5])
        more = f" (+{len(partial) - 5} more)" if len(partial) > 5 else ""
        raise ValueError(f"Ambiguous session '{name}': {names}{more}")
    raise FileNotFoundError(f"No session matching '{name}'")


def list_sessions(session_dir: Path | None = None) -> list[dict[str, Any]]:
    """List available sessions with basic metadata."""
    d = session_dir or default_session_dir()
    if not d.exists():
        return []
    results = []
    for path in sorted(d.glob("*.jsonl"), reverse=True):
        meta: dict[str, Any] = {}
        msg_count = 0
        subagent_count = 0
        models_seen: set[str] = set()
        updated = ""
        preview = ""
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                _apply_state_record(meta, rec)
                ts_value = rec.get("ts")
                if isinstance(ts_value, str) and ts_value:
                    updated = ts_value
                if rec.get("type") == "engine_msg":
                    msg = rec.get("msg", {})
                    if _counts_as_message(msg):
                        msg_count += 1
                        content = str(
                            msg.get("display_content", msg.get("content", "")) or "",
                        ).strip()
                        if content:
                            preview = _preview_text(content)
                    m = rec.get("model")
                    if m:
                        models_seen.add(m)
                elif rec.get("type") == "compact":
                    summary = str(rec.get("summary", "") or "").strip()
                    if summary:
                        preview = _preview_text(summary)
                elif rec.get("type") == "subagent_event" and rec.get("kind") == "start":
                    subagent_count += 1
        results.append({
            "path": str(path),
            "name": path.stem,
            "started": meta.get("started", ""),
            "updated": meta.get("last_active_at", updated),
            "backend": meta.get("backend", "studio"),
            "active_model": meta.get("active_model", "?"),
            "mode": meta.get("mode", "?"),
            "models": sorted(models_seen),
            "messages": msg_count,
            "workspace": meta.get("workspace", ""),
            "preview": meta.get("preview", preview),
            "prompt_tokens": meta.get("prompt_tokens", 0),
            "completion_tokens": meta.get("completion_tokens", 0),
            "tool_calls": meta.get("tool_call_count", 0),
            "subagents": meta.get("subagent_count", subagent_count),
        })
    return results


def export_training(
    path: Path,
    output: Path,
    model_filter: str | None = None,
    *,
    include_thinking: bool = False,
) -> int:
    """Export a session JSONL file to training-format JSONL.

    Each model's conversation becomes one training sample with
    system prompt, user/assistant/tool turns, and metadata.

    Args:
        path: Session JSONL file to convert.
        output: Destination JSONL file.
        model_filter: If set, only export conversations for this model.

    Returns:
        Number of training samples written.
    """
    meta = load_session_bundle(path).meta
    model_msgs: dict[str, list[dict[str, Any]]] = {}

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "engine_msg":
                continue
            model = rec.get("model", "unknown")
            if model_filter and model != model_filter:
                continue
            model_msgs.setdefault(model, []).append(
                _training_message_view(rec["msg"], include_thinking=include_thinking),
            )

    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as out:
        for model, msgs in model_msgs.items():
            if not msgs or not any(msg.get("role") == "assistant" for msg in msgs):
                continue
            sample = {
                "messages": msgs,
                "_metadata": {
                    "source": "z3cli_session",
                    "session": path.stem,
                    "model": model,
                    "mode": meta.get("mode", ""),
                    "workspace": meta.get("workspace", ""),
                },
            }
            out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            count += 1

    return count


def load_session(
    path: Path,
) -> tuple[dict[str, Any], dict[str, list[dict]]]:
    """Load a session file.

    Returns:
        (meta_dict, {model_name: [engine_messages]})

    If a compact record exists for a model, only messages after the
    last compact are included, with the summary injected as the
    starting assistant message.
    """
    loaded = load_session_bundle(path)
    return loaded.meta, loaded.model_messages


def load_session_bundle(path: Path) -> LoadedSession:
    """Load a session file with final state, per-model history, and transcript."""
    return _load_session_bundle(path, include_thinking=True)


def load_session_bundle_without_thinking(path: Path) -> LoadedSession:
    """Load a session file while stripping transcript/subagent reasoning."""
    return _load_session_bundle(path, include_thinking=False)


def load_tool_invocations(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent tool_invocation records from a session file."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "tool_invocation":
                records.append(rec)
    if limit > 0 and len(records) > limit:
        records = records[-limit:]
    return records
