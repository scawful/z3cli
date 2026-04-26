"""Ensure z3cli imports resolve to this repo.

Some developer machines may have a global `services` namespace package earlier on
`sys.path` (e.g. from an unrelated checkout). This repo intentionally uses
top-level imports like `from services...` and `from app...`, so we must ensure
`./src` is first on `sys.path` when running from the repo.

Python automatically imports `sitecustomize` at startup when it is available on
`sys.path`, which is true for `pytest` runs from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_local_src_first() -> None:
    repo_root = Path(__file__).resolve().parent
    src_root = repo_root / "src"
    if not src_root.is_dir():
        return
    src_str = str(src_root)
    if src_str in sys.path:
        sys.path.remove(src_str)
    sys.path.insert(0, src_str)

    for name in ("services", "app"):
        module = sys.modules.get(name)
        if module is None:
            continue
        origin = getattr(getattr(module, "__spec__", None), "origin", "") or ""
        if src_str not in str(origin):
            sys.modules.pop(name, None)


_ensure_local_src_first()
