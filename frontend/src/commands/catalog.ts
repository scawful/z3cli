import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { PaletteEntry } from "../utils/prompt.js";

export interface CommandCatalogEntry {
  name: string;
  args: string;
  description: string;
  group: "quest" | "models" | "tools" | "session";
  groupTitle: string;
  groupSymbol: string;
  aliases?: string;
  paletteLabel?: string;
  paletteDescription?: string;
}

interface CommandCatalogFile {
  welcomeHints: string[];
  commands: CommandCatalogEntry[];
}

function loadCommandCatalog(): CommandCatalogFile {
  const currentDir = path.dirname(fileURLToPath(import.meta.url));
  const candidates = [
    path.join(currentDir, "command_catalog.json"),
    path.join(currentDir, "..", "..", "src", "commands", "command_catalog.json"),
  ];
  const catalogPath = candidates.find((candidate) => existsSync(candidate));
  if (!catalogPath) {
    throw new Error("command catalog file not found");
  }
  const raw = readFileSync(catalogPath, "utf8");
  return JSON.parse(raw) as CommandCatalogFile;
}

function titleCaseCommand(name: string): string {
  return name
    .replace(/^\//, "")
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const COMMAND_CATALOG_FILE = loadCommandCatalog();

export const COMMAND_CATALOG = COMMAND_CATALOG_FILE.commands;

export const COMMAND_GROUPS = Array.from(
  COMMAND_CATALOG.reduce((groups, entry) => {
    const existing = groups.get(entry.group);
    if (existing) {
      existing.entries.push(entry);
      return groups;
    }
    groups.set(entry.group, {
      key: entry.group,
      title: entry.groupTitle,
      symbol: entry.groupSymbol,
      entries: [entry],
    });
    return groups;
  }, new Map<string, { key: string; title: string; symbol: string; entries: CommandCatalogEntry[] }>()),
).map(([, group]) => group);

export const WELCOME_HINTS = COMMAND_CATALOG_FILE.welcomeHints;

export function buildBasePaletteEntries(): PaletteEntry[] {
  return COMMAND_CATALOG.map((entry) => ({
    key: `cmd-${entry.name.slice(1)}`,
    label: entry.paletteLabel ?? titleCaseCommand(entry.name),
    description: entry.paletteDescription ?? entry.description,
    command: entry.name,
    aliases: [entry.aliases, entry.name, entry.description].filter(Boolean).join(" "),
  }));
}
