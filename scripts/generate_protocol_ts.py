#!/usr/bin/env python3
"""Generate frontend IPC transport types from the backend schema."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from z3cli.app.ipc_schema import write_typescript_protocol


def main() -> int:
    out_path = ROOT / "frontend" / "src" / "ipc" / "protocol.generated.ts"
    write_typescript_protocol(out_path)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
