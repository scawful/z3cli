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


CATALOG_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "commands" / "command_catalog.json"


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
        "  oracle-pro                  14B Oracle-Pro · q4km current local pro lane",
        "  oracle-mythic               27B switchhook · q4km manual-heavy model",
        "                              Use /load oracle-mythic before first use when you explicitly want that path",
        "",
        "Inline prompt features:",
        "  @path                       Attach a workspace file to the turn",
        "  #kind:query                 Attach active-project game metadata (for example #room:0x45)",
        "  !cmd                        Run a command in the persistent shell",
    ])
    return "\n".join(lines).rstrip()
