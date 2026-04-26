#!/usr/bin/env python3
"""Generate frontend IPC transport types from the backend schema."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.ipc_schema import write_typescript_protocol


def main() -> int:
    targets = [
        ROOT / "frontend" / "src" / "ipc" / "protocol.generated.ts",
        ROOT / "extensions" / "vscode-z3cli" / "src" / "ipc" / "protocol.generated.ts",
    ]
    for out_path in targets:
        write_typescript_protocol(out_path)
        print(f"Wrote {out_path}")
    catalog_src = ROOT / "frontend" / "src" / "commands" / "command_catalog.json"
    catalog_dst = ROOT / "extensions" / "vscode-z3cli" / "src" / "commands" / "command_catalog.json"
    catalog_dst.parent.mkdir(parents=True, exist_ok=True)
    catalog_dst.write_text(catalog_src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Copied {catalog_dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
