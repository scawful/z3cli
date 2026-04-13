"""Session persistence for z3cli.

Stores conversation history as append-only JSONL files with per-model
engine message tracking, full AppState metadata, and compact support.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SESSION_DIR = Path.home() / ".local/share/z3cli/sessions"


def _slug(text: str, max_words: int = 4) -> str:
    """Generate a short slug from the first few words of text."""
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()[:max_words]
    return "-".join(words) if words else "session"


class Session:
    """Append-only JSONL session file."""

    def __init__(self, session_dir: Path | None = None):
        self._dir = session_dir or DEFAULT_SESSION_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path: Path | None = None
        self._handle = None
        self._msg_count = 0

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def message_count(self) -> int:
        return self._msg_count

    def start(
        self,
        active_model: str,
        backend: str,
        mode: str,
        workspace: str,
        rom_path: str,
        tools_enabled: bool,
        broadcast_models: list[str],
        llamacpp_model: str = "",
    ) -> None:
        """Create a new session file and write the meta record."""
        ts = datetime.now(timezone.utc)
        name = ts.strftime("%Y-%m-%d_%H%M%S")
        self._path = self._dir / f"{name}.jsonl"
        self._handle = self._path.open("a", encoding="utf-8")
        self._write({
            "type": "meta",
            "active_model": active_model,
            "backend": backend,
            "mode": mode,
            "workspace": workspace,
            "rom_path": rom_path,
            "tools_enabled": tools_enabled,
            "broadcast_models": broadcast_models,
            "llamacpp_model": llamacpp_model,
            "started": ts.isoformat(),
        })

    def append_engine_msg(self, model: str, msg: dict) -> None:
        """Append an engine message record tagged with the model name."""
        self._write({"type": "engine_msg", "model": model, "msg": msg})
        if msg.get("role") in ("user", "assistant"):
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

    def save_compact(self, model: str, summary: str, replaced_count: int) -> None:
        self._write({
            "type": "compact",
            "model": model,
            "summary": summary,
            "replaced_count": replaced_count,
        })

    def rename_from_first_message(self, text: str) -> None:
        """Rename the session file based on the first user message."""
        if self._path is None:
            return
        slug = _slug(text)
        stem = self._path.stem
        new_name = f"{stem}_{slug}.jsonl"
        new_path = self._path.parent / new_name
        if new_path.exists() or self._path.name.count("_") > 2:
            return  # Already renamed or collision
        if self._handle:
            self._handle.close()
        self._path.rename(new_path)
        self._path = new_path
        self._handle = self._path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._handle:
            self._handle.close()
            self._handle = None

    def _write(self, record: dict) -> None:
        if self._handle is None:
            return
        record["ts"] = datetime.now(timezone.utc).isoformat()
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()


# ---------------------------------------------------------------------------
# Loading / listing
# ---------------------------------------------------------------------------

def list_sessions(session_dir: Path | None = None) -> list[dict[str, Any]]:
    """List available sessions with basic metadata."""
    d = session_dir or DEFAULT_SESSION_DIR
    if not d.exists():
        return []
    results = []
    for path in sorted(d.glob("*.jsonl"), reverse=True):
        meta = {}
        msg_count = 0
        models_seen: set[str] = set()
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "meta":
                    meta = rec
                elif rec.get("type") == "engine_msg":
                    if rec.get("msg", {}).get("role") in ("user", "assistant"):
                        msg_count += 1
                    m = rec.get("model")
                    if m:
                        models_seen.add(m)
        results.append({
            "path": str(path),
            "name": path.stem,
            "started": meta.get("started", ""),
            "backend": meta.get("backend", "studio"),
            "active_model": meta.get("active_model", "?"),
            "mode": meta.get("mode", "?"),
            "models": sorted(models_seen),
            "messages": msg_count,
        })
    return results


def export_training(
    path: Path,
    output: Path,
    model_filter: str | None = None,
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
    meta: dict[str, Any] = {}
    model_msgs: dict[str, list[dict]] = {}

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "meta":
                meta = rec
            elif rec.get("type") == "engine_msg":
                model = rec.get("model", "unknown")
                if model_filter and model != model_filter:
                    continue
                model_msgs.setdefault(model, []).append(rec["msg"])

    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as out:
        for model, msgs in model_msgs.items():
            if not msgs or not any(m.get("role") == "assistant" for m in msgs):
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
    meta: dict[str, Any] = {}
    # Collect all engine_msg records grouped by model
    all_msgs: dict[str, list[dict]] = {}
    # Track compact points per model
    compact_points: dict[str, tuple[str, int]] = {}  # model -> (summary, record_index)
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
            if rtype == "meta":
                meta = rec
            elif rtype == "engine_msg":
                model = rec.get("model", "unknown")
                if model not in all_msgs:
                    all_msgs[model] = []
                all_msgs[model].append({"_idx": record_idx, **rec["msg"]})
            elif rtype == "compact":
                model = rec.get("model", "unknown")
                compact_points[model] = (rec.get("summary", ""), record_idx)

            record_idx += 1

    # Apply compaction: for each model with a compact record, only keep
    # messages after the compact, prepended with the summary
    result: dict[str, list[dict]] = {}
    for model, msgs in all_msgs.items():
        if model in compact_points:
            summary, compact_idx = compact_points[model]
            # Keep only messages recorded after the compact
            msgs = [m for m in msgs if m.get("_idx", 0) > compact_idx]
            # Prepend the compact summary as an assistant message
            msgs.insert(0, {"role": "assistant", "content": summary})
        # Strip internal index markers
        result[model] = [{k: v for k, v in m.items() if k != "_idx"} for m in msgs]

    return meta, result
