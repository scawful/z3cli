"""asar ``namespace X`` prefixes assembled labels (``Oracle_Foo`` in .mlb/.sym) but not the source."""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path

_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:;.*)?$")
_MAX_FILES = 5000


@functools.lru_cache(maxsize=8)
def workspace_namespaces(workspace: str) -> tuple[str, ...]:
    found: set[str] = set()
    count = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"build", "node_modules"}]
        for name in files:
            if not name.lower().endswith((".asm", ".inc", ".s")):
                continue
            count += 1
            if count > _MAX_FILES:
                return tuple(sorted(found))
            try:
                text = Path(root, name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "namespace" not in text:
                continue
            for line in text.splitlines():
                match = _NAMESPACE_RE.match(line)
                if match and match.group(1) not in {"off", "nested"}:
                    found.add(match.group(1))
    return tuple(sorted(found))


def strip_namespace(query: str, workspace: Path) -> str | None:
    """``Oracle_Follower_WatchLink`` -> ``Follower_WatchLink`` when ``Oracle`` is a workspace namespace."""
    for namespace in workspace_namespaces(str(workspace)):
        prefix = f"{namespace}_"
        if query.startswith(prefix) and len(query) > len(prefix):
            return query[len(prefix):]
    return None


def namespace_note(query: str, stripped: str) -> str:
    return f"(no matches for {query}; retried without the asar namespace prefix: {stripped})"
