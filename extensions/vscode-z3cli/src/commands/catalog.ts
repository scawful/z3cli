import catalogJson from "./command_catalog.json";

export interface CommandCatalogEntry {
  name: string;
  args: string;
  description: string;
  group: string;
  groupTitle: string;
  groupSymbol: string;
  aliases?: string;
  paletteLabel?: string;
  paletteDescription?: string;
}

export interface CommandCatalogFile {
  welcomeHints: string[];
  commands: CommandCatalogEntry[];
}

const catalog = catalogJson as CommandCatalogFile;

export const COMMAND_CATALOG: CommandCatalogEntry[] = catalog.commands;
export const WELCOME_HINTS: string[] = catalog.welcomeHints;

export interface CommandGroup {
  key: string;
  title: string;
  symbol: string;
  entries: CommandCatalogEntry[];
}

export const COMMAND_GROUPS: CommandGroup[] = (() => {
  const groups = new Map<string, CommandGroup>();
  for (const entry of COMMAND_CATALOG) {
    const existing = groups.get(entry.group);
    if (existing) {
      existing.entries.push(entry);
    } else {
      groups.set(entry.group, {
        key: entry.group,
        title: entry.groupTitle,
        symbol: entry.groupSymbol,
        entries: [entry],
      });
    }
  }
  return Array.from(groups.values());
})();

export function findEntry(slash: string): CommandCatalogEntry | undefined {
  return COMMAND_CATALOG.find((entry) => entry.name === slash);
}
