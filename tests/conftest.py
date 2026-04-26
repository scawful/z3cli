from __future__ import annotations

import sys
from pathlib import Path


def _prepend_repo_src() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if not src_root.is_dir():
        return
    src_str = str(src_root)
    if sys.path and sys.path[0] == src_str:
        return
    if src_str in sys.path:
        sys.path.remove(src_str)
    sys.path.insert(0, src_str)

    # If an unrelated namespace package named `services` was imported earlier
    # (e.g. via a global PYTHONPATH), drop it so imports resolve to this repo.
    for name in ("services", "app"):
        module = sys.modules.get(name)
        if module is None:
            continue
        origin = getattr(getattr(module, "__spec__", None), "origin", "") or ""
        if src_str not in str(origin):
            sys.modules.pop(name, None)


_prepend_repo_src()
