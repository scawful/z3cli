"""A Python stand-in for the z3ed binary, shared by the bridge tests."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path


def _write_fake_z3ed(
    target: Path,
    *,
    schemas: dict | None = None,
    response: str = '{"ok": true}',
    fail: bool = False,
) -> None:
    """Write a fake z3ed that serves ``schemas`` and appends its argv to $FAKE_Z3ED_RECORD."""
    payload_json = json.dumps(schemas or {"commands": []})
    body = f"""#!{sys.executable}
import json, os, sys

if "--export-schemas" in sys.argv:
    sys.stdout.write({payload_json!r})
    sys.exit(0)

recorder = os.environ.get("FAKE_Z3ED_RECORD")
if recorder:
    with open(recorder, "a") as f:
        f.write(" ".join(sys.argv[1:]) + chr(10))

if {fail!r}:
    sys.stderr.write("simulated failure")
    sys.exit(2)

sys.stdout.write({response!r})
sys.exit(0)
"""
    target.write_text(body)
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
