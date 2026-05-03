from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict


class CommandCatalogEntry(TypedDict, total=False):
    name: str
    args: str
    description: str
    group: str
    groupTitle: str
    groupSymbol: str
    aliases: str
    paletteLabel: str
    paletteDescription: str


class CommandCatalogFile(TypedDict):
    welcomeHints: list[str]
    commands: list[CommandCatalogEntry]


def _source_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "frontend" / "src" / "commands" / "command_catalog.json").is_file():
            return parent
    return Path.cwd()


CATALOG_PATH = _source_root() / "frontend" / "src" / "commands" / "command_catalog.json"


@lru_cache(maxsize=1)
def load_command_catalog() -> CommandCatalogFile:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {
        "welcomeHints": [str(item) for item in payload.get("welcomeHints", []) if isinstance(item, str)],
        "commands": [
            {
                key: value
                for key, value in entry.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            for entry in payload.get("commands", [])
            if isinstance(entry, dict)
        ],
    }


def command_groups() -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for entry in load_command_catalog()["commands"]:
        group_key = str(entry.get("group", "misc") or "misc")
        if group_key not in grouped:
            grouped[group_key] = {
                "key": group_key,
                "title": str(entry.get("groupTitle", group_key.title()) or group_key.title()),
                "symbol": str(entry.get("groupSymbol", "-") or "-"),
                "entries": [],
            }
            order.append(group_key)
        cast_entries = grouped[group_key]["entries"]
        assert isinstance(cast_entries, list)
        cast_entries.append(entry)
    return [grouped[key] for key in order]


def build_repl_help_text() -> str:
    lines = ["Commands:"]
    for group in command_groups():
        lines.append(f"  {group['symbol']} {group['title']}")
        entries = group["entries"]
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            usage = f"{entry.get('name', '')} {entry.get('args', '')}".rstrip()
            lines.append(f"    {usage:<28} {entry.get('description', '')}")
        lines.append("")
    lines.extend([
        "Model notes:",
        "  oracle                      14B Oracle v8 · q4km installed local default",
        "  oracle-9b-router            9B Oracle v5 guarded by the 14B teacher-router policy",
        "  oracle-qwen35-9b           configured 9B Oracle lane; appears when installed",
        "  oracle-pro                  advanced/manual Oracle-Pro v8 alias",
        "                              Use /route oracle-pro-ssh when local SSH tunnels are unavailable",
        "  oracle-mythic               27B switchhook · q4km manual-heavy model",
        "                              Use /load oracle-mythic before first use when you explicitly want that path",
        "  oracle-coder-pro            hidden Qwen3-Coder 30B sidecar for Oracle-Pro delegation",
        "  oracle-reasoner-27b         hidden Qwen3.6 27B sidecar for strategy/review delegation",
        "",
        "Inline prompt features:",
        "  @path                       Attach a workspace file to the turn",
        "  #kind:query                 Attach active-project game metadata (for example #room:0x45)",
        "  !cmd                        Run a command in the persistent shell",
    ])
    return "\n".join(lines).rstrip()
