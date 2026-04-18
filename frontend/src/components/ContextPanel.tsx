import React from "react";
import { Box, Text } from "ink";
import type { AppConfig, AttachmentMeta, ConstructRef } from "../ipc/protocol.js";
import type { SessionInfo } from "../commands/index.js";
import { heartBar, modelColor, modelSymbol, symbols, formatTokens } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { basename, shortenPath } from "../utils/path.js";
import { describeLoadedModelRuntime, formatModelMemory } from "../utils/models.js";
import { constructToken } from "../utils/prompt.js";

interface ContextPanelProps {
  config: AppConfig;
  contextPercent: number;
  contextWindow: number;
  promptTokens: number;
  completionTokens: number;
  userMessageCount: number;
  recentSessions: SessionInfo[];
  draftFiles: AttachmentMeta[];
  draftConstructRefs: ConstructRef[];
  width?: number;
  viewportHeight?: number;
}

function sessionName(name: string): string {
  return name.replace(/^\d{4}-\d{2}-\d{2}_\d{6}(?:_\d+)?_?/, "") || name;
}

function formatCompactCount(count: number): string {
  if (count >= 10_000) return `${Math.round(count / 1000)}k`;
  if (count >= 1_000) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

export interface ContextPanelLimits {
  compact: boolean;
  draftFilesLimit: number;
  recentSessionsLimit: number;
  loadedModelsLimit: number;
}

export function deriveContextPanelLimits(
  width: number,
  viewportHeight: number,
): ContextPanelLimits {
  const veryTight = viewportHeight <= 16;
  const compact = width < 36 || viewportHeight <= 20;
  return {
    compact,
    draftFilesLimit: veryTight ? 3 : compact ? 4 : 5,
    recentSessionsLimit: veryTight ? 2 : compact ? 3 : 4,
    loadedModelsLimit: veryTight ? 2 : compact ? 3 : 4,
  };
}

export function buildLoadedModelLines(config: AppConfig, lineLimit: number): string[] {
  return (config.loadedModels ?? [])
    .slice(0, lineLimit)
    .map((entry) => {
      const runtime = describeLoadedModelRuntime({
        sizeBytes: entry.sizeBytes,
        status: entry.status,
        parallel: entry.parallel,
        queued: entry.queued,
        contextLength: entry.contextLength,
        quantization: entry.quantization,
        estimatedGpuBytes: entry.estimatedGpuBytes,
        estimatedTotalBytes: entry.estimatedTotalBytes,
      });
      const label = entry.identifier || entry.displayName || entry.modelKey;
      return [label, runtime].filter(Boolean).join(" · ");
    });
}

export function ContextPanel({
  config,
  contextPercent,
  contextWindow,
  promptTokens,
  completionTokens,
  userMessageCount,
  recentSessions,
  draftFiles,
  draftConstructRefs,
  width = 36,
  viewportHeight = 20,
}: ContextPanelProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const totalTokens = promptTokens + completionTokens;
  const tokenDisplay = formatTokens(totalTokens, colors);
  const hearts = heartBar(contextPercent, 10, colors);
  const tokenText = tokenDisplay.text || `${symbols.rupee} 0`;
  const tokenColor = tokenDisplay.text ? tokenDisplay.color : colors.dim;
  const limits = deriveContextPanelLimits(width, viewportHeight);
  const rules = config.permissionRules ?? {};
  const allowCount = Object.values(rules).filter(Boolean).length;
  const denyCount = Object.values(rules).filter((value) => !value).length;
  const cancelCount = config.cancelCount ?? 0;
  const restartCount = config.backendRestartCount ?? 0;
  const loadedModels = config.loadedModels ?? [];
  const loadedModelLines = buildLoadedModelLines(config, limits.loadedModelsLimit);
  const loadedModelCount = config.loadedModelCount ?? loadedModels.length;
  const loadedModelMemoryText = formatModelMemory(config.loadedModelMemoryBytes);

  return (
    <Box width={width} flexDirection="column" gap={1}>
      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Map & Context</Text>
        <Box gap={1}>
          <Text color={modelColor(config.activeModel, colors)}>{modelSymbol(config.activeModel)}</Text>
          <Text color={modelColor(config.activeModel, colors)} bold>{config.activeModel}</Text>
          <Text dimColor>{config.backend}</Text>
        </Box>
        <Text dimColor>{shortenPath(config.workspace)}</Text>
        {config.focusFile ? (
          <Text color={colors.nayru}>{symbols.pendant} {basename(config.focusFile)}</Text>
        ) : null}
        {contextWindow > 0 ? (
          <Box gap={1}>
            <Text color={hearts.color}>{hearts.display}</Text>
            <Text dimColor>{contextPercent}% of {formatCompactCount(contextWindow)}</Text>
          </Box>
        ) : null}
        <Box gap={1}>
          <Text color={tokenColor}>{tokenText}</Text>
          <Text dimColor>{config.servers.length} servers · {config.toolCount} tools</Text>
        </Box>
        {loadedModelCount > 0 ? (
          <Text dimColor>load {loadedModelCount} · {loadedModelMemoryText || "tracked"}</Text>
        ) : null}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Session</Text>
        <Text dimColor>{userMessageCount} user turns · {config.sessionToolCalls ?? 0} tool calls</Text>
        <Text dimColor>rules {allowCount} allow · {denyCount} deny</Text>
        <Text dimColor>verify {config.verifyHooks === false ? "off" : "on"}</Text>
        {config.shellActive ? (
          <Text dimColor>shell active · {shortenPath(config.shellCwd ?? config.workspace)}</Text>
        ) : null}
        {cancelCount > 0 || restartCount > 0 ? (
          <Text dimColor>cancel {cancelCount} · restart {restartCount}</Text>
        ) : null}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Loaded Models</Text>
        {loadedModels.length === 0 ? (
          <Text dimColor>none</Text>
        ) : (
          <>
            <Text dimColor>{loadedModelCount} live · {loadedModelMemoryText || "memory n/a"}</Text>
            {loadedModelLines.map((line) => (
              <Text key={line} dimColor>{line}</Text>
            ))}
          </>
        )}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Inventory (@files)</Text>
        {draftFiles.length === 0 ? (
          <Text dimColor>none</Text>
        ) : (
          draftFiles.slice(0, limits.draftFilesLimit).map((file) => (
            <Text key={file.path} color={colors.nayru}>
              {[
                file.path,
                file.lines > 0 ? `${file.lines}L` : "",
                file.chars > 0 ? `${file.chars}C` : "",
              ].filter(Boolean).join(" ")}
            </Text>
          ))
        )}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Glyphs (#refs)</Text>
        {draftConstructRefs.length === 0 ? (
          <Text dimColor>none</Text>
        ) : (
          draftConstructRefs.slice(0, limits.draftFilesLimit).map((ref) => (
            <Text key={constructToken(ref)} color={colors.accent}>
              {constructToken(ref)}{ref.label ? ` ${ref.label}` : ""}
            </Text>
          ))
        )}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Quest Log (Recent)</Text>
        {recentSessions.length === 0 ? (
          <Text dimColor>no saved sessions</Text>
        ) : (
          recentSessions.slice(0, limits.recentSessionsLimit).map((session) => (
            <Box key={session.name} gap={1}>
              <Text color={modelColor(session.activeModel, colors)}>{modelSymbol(session.activeModel)}</Text>
              <Text color={colors.text}>{sessionName(session.name)}</Text>
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
}
