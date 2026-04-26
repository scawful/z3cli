import React, { useEffect, useMemo, useState } from "react";
import { Box, Text, useInput } from "ink";
import type { AppConfig, LoadedModelInfo, ModelInfo } from "../ipc/protocol.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { describeLoadedModelRuntime, formatModelEstimate, formatModelMemory } from "../utils/models.js";
import { modelColor, modelSymbol, symbols } from "../theme/index.js";

const VISIBLE_ROWS = 10;
const ORACLE_MODEL_ORDER = [
  "oracle-fast",
  "oracle-qwen35-9b",
  "oracle",
  "oracle-pro",
  "qwen3-oracle-14b",
] as const;
const BENCH_MODEL_ORDER = [
  "qwen3-oracle-8b",
  "din",
  "nayru",
  "navi",
  "navi-q4km",
  "oracle-coder",
] as const;
const QWEN_MODEL_ORDER = [
  "qwen3-local-8b",
  "qwen3-local-14b",
] as const;
const CLOUD_MODEL_ORDER = ["claude-sonnet", "claude-opus", "gpt-4o"] as const;
const FAMILY_ORDER = ["oracle", "bench", "qwen", "cloud", "resident", "other"] as const;
const FAMILY_LABELS = {
  oracle: "Oracle",
  bench: "Bench",
  qwen: "Qwen",
  cloud: "Cloud",
  resident: "Resident",
  other: "Other",
} as const;
const ORACLE_MODELS = new Set<string>([
  "oracle",
  "oracle-pro",
  "oracle-fast",
  "oracle-qwen35-9b",
  "qwen3-oracle-14b",
]);
const BENCH_MODELS = new Set<string>([
  "qwen3-oracle-8b",
  "din",
  "nayru",
  "navi",
  "navi-q4km",
  "oracle-coder",
]);

type ModelManagerFamily = typeof FAMILY_ORDER[number];

export interface ModelManagerEntry {
  key: string;
  name: string;
  subtitle: string;
  runtime: string;
  estimate: string;
  active: boolean;
  loaded: boolean;
  canActivate: boolean;
  canLoad: boolean;
  canUnload: boolean;
  actionTarget: string;
  family: ModelManagerFamily;
  catalogTag: string;
}

export interface ModelManagerTab {
  key: ModelManagerFamily;
  label: string;
  entries: ModelManagerEntry[];
}

function loadedLookupKeys(entry: LoadedModelInfo): string[] {
  return [entry.identifier, entry.modelKey, entry.displayName].filter(Boolean) as string[];
}

function findLoadedModel(model: ModelInfo, loadedModels: LoadedModelInfo[]): LoadedModelInfo | undefined {
  const candidates = [model.loadedIdentifier, model.modelId, model.name].filter(Boolean) as string[];
  return loadedModels.find((entry) => loadedLookupKeys(entry).some((key) => candidates.includes(key)));
}

function compactModelId(modelId: string): string {
  if (modelId.length <= 52) return modelId;
  return `${modelId.slice(0, 24)}...${modelId.slice(-24)}`;
}

function inferModelManagerFamily(model: ModelInfo): ModelManagerFamily {
  const name = model.name.toLowerCase();
  if (model.provider && model.provider !== "studio" && model.provider !== "llamacpp" && model.provider !== "ollama") {
    return "cloud";
  }
  if (BENCH_MODELS.has(name)) {
    return "bench";
  }
  if (ORACLE_MODELS.has(name) || name.startsWith("oracle")) {
    return "oracle";
  }
  if (name.startsWith("qwen")) {
    return "qwen";
  }
  return "other";
}

function familyOrderIndex(family: ModelManagerFamily): number {
  return FAMILY_ORDER.indexOf(family);
}

function familyModelRank(family: ModelManagerFamily, name: string): number {
  const lowered = name.toLowerCase();
  if (family === "oracle") {
    return ORACLE_MODEL_ORDER.indexOf(lowered as (typeof ORACLE_MODEL_ORDER)[number]);
  }
  if (family === "bench") {
    return BENCH_MODEL_ORDER.indexOf(lowered as (typeof BENCH_MODEL_ORDER)[number]);
  }
  if (family === "qwen") {
    return QWEN_MODEL_ORDER.indexOf(lowered as (typeof QWEN_MODEL_ORDER)[number]);
  }
  if (family === "cloud") {
    return CLOUD_MODEL_ORDER.indexOf(lowered as (typeof CLOUD_MODEL_ORDER)[number]);
  }
  return -1;
}

function modelCatalogTag(model: ModelInfo, selectable: boolean, primaryListed: boolean): string {
  if (model.name === "oracle-coder") {
    return "internal";
  }
  if (model.name === "oracle-pro") {
    return "manual";
  }
  if (selectable && !primaryListed) {
    return "catalog";
  }
  if (selectable) {
    return "";
  }
  return "catalog";
}

export function buildModelManagerEntries(config: AppConfig): ModelManagerEntry[] {
  const loadedModels = config.loadedModels ?? [];
  const primaryNames = new Set(config.models.map((model) => model.name));
  const catalogModels = config.modelCatalog ?? config.models;
  const matchedLoaded = new Set<string>();
  const entries: ModelManagerEntry[] = catalogModels.map((model) => {
    const studioManaged = !model.provider || model.provider === "studio";
    const loaded = findLoadedModel(model, loadedModels);
    if (loaded) {
      matchedLoaded.add(loaded.identifier || loaded.modelKey);
    }
    const family = inferModelManagerFamily(model);
    const canActivate = Boolean(model.selectable ?? true);
    const primaryListed = primaryNames.has(model.name);
    const runtime = describeLoadedModelRuntime({
      sizeBytes: model.sizeBytes,
      status: model.status,
      parallel: model.parallel,
      queued: model.queued,
      contextLength: model.contextLength,
      quantization: model.quantization,
      estimatedGpuBytes: model.estimatedGpuBytes,
      estimatedTotalBytes: model.estimatedTotalBytes,
    });
    return {
      key: `model-${model.name}`,
      name: model.name,
      subtitle: [model.role, model.provider, compactModelId(model.modelId)].filter(Boolean).join(" · "),
      runtime,
      estimate: formatModelEstimate(model.estimatedGpuBytes, model.estimatedTotalBytes),
      active: model.name === config.activeModel,
      loaded: model.loaded,
      canActivate,
      canLoad: config.backend === "studio" && studioManaged && !model.loaded,
      canUnload: config.backend === "studio" && studioManaged && model.loaded,
      actionTarget: model.loadedIdentifier || model.modelId || model.name,
      family,
      catalogTag: modelCatalogTag(model, canActivate, primaryListed),
    };
  });

  for (const loaded of loadedModels) {
    const loadedKey = loaded.identifier || loaded.modelKey;
    if (!loadedKey || matchedLoaded.has(loadedKey)) continue;
    entries.push({
      key: `resident-${loadedKey}`,
      name: loaded.identifier || loaded.displayName || loaded.modelKey,
      subtitle: `resident only · ${compactModelId(loaded.modelKey)}`,
      runtime: describeLoadedModelRuntime({
        sizeBytes: loaded.sizeBytes,
        status: loaded.status,
        parallel: loaded.parallel,
        queued: loaded.queued,
        contextLength: loaded.contextLength,
        quantization: loaded.quantization,
        estimatedGpuBytes: loaded.estimatedGpuBytes,
        estimatedTotalBytes: loaded.estimatedTotalBytes,
      }),
      estimate: formatModelEstimate(loaded.estimatedGpuBytes, loaded.estimatedTotalBytes),
      active: false,
      loaded: true,
      canActivate: false,
      canLoad: false,
      canUnload: config.backend === "studio",
      actionTarget: loaded.identifier || loaded.modelKey,
      family: "resident",
      catalogTag: "resident",
    });
  }

  return entries.sort((left, right) => {
    const familyDelta = familyOrderIndex(left.family) - familyOrderIndex(right.family);
    if (familyDelta !== 0) return familyDelta;
    const leftRank = familyModelRank(left.family, left.name);
    const rightRank = familyModelRank(right.family, right.name);
    if (leftRank !== rightRank) {
      if (leftRank === -1) return 1;
      if (rightRank === -1) return -1;
      return leftRank - rightRank;
    }
    if (left.loaded !== right.loaded) return left.loaded ? -1 : 1;
    return left.name.localeCompare(right.name);
  });
}

export function buildModelManagerTabs(config: AppConfig): ModelManagerTab[] {
  const grouped = new Map<ModelManagerFamily, ModelManagerEntry[]>();
  for (const entry of buildModelManagerEntries(config)) {
    const bucket = grouped.get(entry.family) ?? [];
    bucket.push(entry);
    grouped.set(entry.family, bucket);
  }
  return FAMILY_ORDER.flatMap((family) => {
    const entries = grouped.get(family) ?? [];
    if (entries.length === 0) {
      return [];
    }
    return [{
      key: family,
      label: FAMILY_LABELS[family],
      entries,
    }];
  });
}

interface ModelManagerPanelProps {
  config: AppConfig;
  onClose: () => void;
}

export function ModelManagerPanel({ config, onClose }: ModelManagerPanelProps): React.ReactElement {
  const { colors, execCommand } = useSettingsContext();
  const tabs = useMemo(() => buildModelManagerTabs(config), [config]);
  const [selectedTabKey, setSelectedTabKey] = useState<ModelManagerFamily | "">("");
  const [index, setIndex] = useState(0);
  const tabIndex = Math.max(0, tabs.findIndex((tab) => tab.key === selectedTabKey));
  const selectedTab = tabs[tabIndex] ?? tabs[0];
  const entries = selectedTab?.entries ?? [];

  useEffect(() => {
    const activeEntryTab = tabs.findIndex((tab) => tab.entries.some((entry) => entry.active));
    setSelectedTabKey((current) => {
      if (tabs.length === 0) {
        return "";
      }
      if (current && tabs.some((tab) => tab.key === current)) {
        return current;
      }
      if (activeEntryTab >= 0) {
        return tabs[activeEntryTab]?.key ?? tabs[0].key;
      }
      return tabs[0].key;
    });
  }, [tabs]);

  useEffect(() => {
    setIndex((current) => Math.max(0, Math.min(current, entries.length - 1)));
  }, [entries.length]);

  const selected = entries[index];
  const loadedModelCount = config.loadedModelCount ?? (config.loadedModels?.length ?? 0);
  const loadedMemory = formatModelMemory(config.loadedModelMemoryBytes);
  const visibleStart = Math.max(0, Math.min(index - Math.floor(VISIBLE_ROWS / 2), Math.max(0, entries.length - VISIBLE_ROWS)));
  const visibleEntries = entries.slice(visibleStart, visibleStart + VISIBLE_ROWS);

  useInput((input, key) => {
    const lower = input.toLowerCase();
    if (key.escape || lower === "q") {
      onClose();
      return;
    }
    if (key.upArrow) {
      setIndex((current) => Math.max(0, current - 1));
      return;
    }
    if (key.leftArrow && tabs.length > 1) {
      setSelectedTabKey(tabs[(tabIndex - 1 + tabs.length) % tabs.length]?.key ?? "");
      setIndex(0);
      return;
    }
    if (key.rightArrow && tabs.length > 1) {
      setSelectedTabKey(tabs[(tabIndex + 1) % tabs.length]?.key ?? "");
      setIndex(0);
      return;
    }
    if (key.downArrow) {
      setIndex((current) => Math.min(Math.max(0, entries.length - 1), current + 1));
      return;
    }
    if (key.pageUp) {
      setIndex((current) => Math.max(0, current - VISIBLE_ROWS));
      return;
    }
    if (key.pageDown) {
      setIndex((current) => Math.min(Math.max(0, entries.length - 1), current + VISIBLE_ROWS));
      return;
    }
    if ((key.return || input === "\r") && selected?.canActivate) {
      execCommand?.("/model", [selected.name]);
      return;
    }
    if (lower === "l" && selected?.canLoad) {
      execCommand?.("/load", [selected.name]);
      return;
    }
    if (lower === "u" && selected?.canUnload) {
      execCommand?.("/unload", [selected.actionTarget]);
      return;
    }
    if (lower === "a" && config.backend === "studio" && loadedModelCount > 0) {
      execCommand?.("/unload", ["all"]);
    }
  });

  return (
    <Box borderStyle="double" borderColor={colors.triforce} paddingX={1} paddingY={1} flexDirection="column">
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text bold color={colors.triforce}>{symbols.compass} Oracle Register</Text>
          <Text dimColor>{config.backend}</Text>
        </Box>
        <Text dimColor>Esc/q close</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text color={colors.text}>{loadedModelCount} loaded{loadedMemory ? ` ${symbols.dot} ${loadedMemory}` : ""}</Text>
        <Text dimColor>
          {tabs.length > 1 ? `←/→ sections ${symbols.dot} ` : ""}Enter switch active {symbols.dot} L load {symbols.dot} U unload {symbols.dot} A unload all
        </Text>
        {config.backend !== "studio" ? (
          <Text color={colors.warning}>load/unload controls are only active on the studio backend</Text>
        ) : null}
      </Box>

      <Box marginTop={1} gap={1} flexWrap="wrap">
        {tabs.map((tab, currentTabIndex) => {
          const activeTab = currentTabIndex === tabIndex;
          return (
            <Text key={tab.key} color={activeTab ? colors.triforce : colors.dim} bold={activeTab}>
              [{tab.label}]
            </Text>
          );
        })}
      </Box>

      <Box marginTop={1} flexDirection="column">
        {visibleStart > 0 ? <Text dimColor>↑ {visibleStart} more</Text> : null}
        {visibleEntries.map((entry, visibleIndex) => {
          const absoluteIndex = visibleStart + visibleIndex;
          const selectedRow = absoluteIndex === index;
          const tint = entry.canActivate ? modelColor(entry.name, colors) : colors.oracleTools;
          const marker = entry.canActivate ? modelSymbol(entry.name) : symbols.shield;
          return (
            <Box key={entry.key} marginTop={visibleIndex === 0 ? 0 : 1} flexDirection="column">
              <Box gap={1}>
                <Text color={selectedRow ? colors.triforce : colors.dim}>{selectedRow ? symbols.arrowRight : " "}</Text>
                <Text color={tint}>{marker}</Text>
                <Text color={tint} bold={selectedRow || entry.active}>{entry.name}</Text>
                {entry.active ? <Text color={colors.triforce}>current</Text> : null}
                {entry.loaded ? <Text color={colors.success}>loaded</Text> : null}
                {!entry.loaded && entry.canLoad ? <Text dimColor>available</Text> : null}
                {entry.catalogTag ? <Text dimColor>{entry.catalogTag}</Text> : null}
              </Box>
              <Box paddingLeft={3} flexDirection="column">
                <Text dimColor>{entry.subtitle}</Text>
                {entry.runtime ? <Text color={entry.loaded ? colors.success : colors.muted}>{entry.runtime}</Text> : null}
                {!entry.runtime && entry.estimate ? <Text color={colors.muted}>{entry.estimate}</Text> : null}
              </Box>
            </Box>
          );
        })}
        {visibleStart + visibleEntries.length < entries.length ? (
          <Text dimColor>↓ {entries.length - (visibleStart + visibleEntries.length)} more</Text>
        ) : null}
      </Box>
    </Box>
  );
}
