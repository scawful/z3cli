"""Import shim for `services.*`.

z3cli implementation code lives under `src/services`, but many modules import
`services.*` directly. On machines that also have an unrelated `services`
package on `PYTHONPATH`, imports can resolve to the wrong tree.

This shim ensures that `./src` is on `sys.path` and that `services` resolves to
this repository's implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from pkgutil import extend_path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"

if _SRC_ROOT.is_dir():
    src_str = str(_SRC_ROOT)
    if src_str in sys.path:
        sys.path.remove(src_str)
    sys.path.insert(0, src_str)

# Make `services` a pkgutil namespace so `src/services/*` is discoverable.
__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]
