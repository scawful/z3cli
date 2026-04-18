import React, { useEffect, useMemo, useState } from "react";
import { Box, Text, useInput } from "ink";
import type { AppConfig, LoadedModelInfo, ModelInfo } from "../ipc/protocol.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { describeLoadedModelRuntime, formatModelEstimate, formatModelMemory } from "../utils/models.js";
import { modelColor, modelSymbol, symbols } from "../theme/index.js";

const VISIBLE_ROWS = 10;

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

export function buildModelManagerEntries(config: AppConfig): ModelManagerEntry[] {
  const loadedModels = config.loadedModels ?? [];
  const matchedLoaded = new Set<string>();
  const entries: ModelManagerEntry[] = config.models.map((model) => {
    const studioManaged = !model.provider || model.provider === "studio";
    const loaded = findLoadedModel(model, loadedModels);
    if (loaded) {
      matchedLoaded.add(loaded.identifier || loaded.modelKey);
    }
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
      canActivate: true,
      canLoad: config.backend === "studio" && studioManaged && !model.loaded,
      canUnload: config.backend === "studio" && studioManaged && model.loaded,
      actionTarget: model.loadedIdentifier || model.modelId || model.name,
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
    });
  }

  return entries.sort((left, right) => {
    if (left.active !== right.active) return left.active ? -1 : 1;
    if (left.loaded !== right.loaded) return left.loaded ? -1 : 1;
    return left.name.localeCompare(right.name);
  });
}

interface ModelManagerPanelProps {
  config: AppConfig;
  onClose: () => void;
}

export function ModelManagerPanel({ config, onClose }: ModelManagerPanelProps): React.ReactElement {
  const { colors, execCommand } = useSettingsContext();
  const entries = useMemo(() => buildModelManagerEntries(config), [config]);
  const [index, setIndex] = useState(0);

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
          Enter switch active {symbols.dot} L load {symbols.dot} U unload {symbols.dot} A unload all
        </Text>
        {config.backend !== "studio" ? (
          <Text color={colors.warning}>load/unload controls are only active on the studio backend</Text>
        ) : null}
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
