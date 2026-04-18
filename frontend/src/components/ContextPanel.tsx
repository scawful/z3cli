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
  diagnosticsLineLimit: number;
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
    diagnosticsLineLimit: veryTight ? 4 : compact ? 5 : 7,
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
      });
      const label = entry.identifier || entry.displayName || entry.modelKey;
      return [label, runtime].filter(Boolean).join(" · ");
    });
}

export function buildDiagnosticsLines(
  config: AppConfig,
  lineLimit: number,
  compact: boolean,
): string[] {
  const toolLatencyMs = config.toolLatencyMs ?? 0;
  const toolLatencySamples = config.toolLatencySamples ?? 0;
  const permissionWaitMs = config.permissionWaitMs ?? 0;
  const reviewWaitMs = config.reviewWaitMs ?? 0;
  const permissionTimeouts = config.permissionTimeoutCount ?? 0;
  const reviewTimeouts = config.reviewTimeoutCount ?? 0;
  const modelRetries = config.modelRetryCount ?? 0;
  const modelRetryBackoffMs = config.modelRetryBackoffMs ?? 0;
  const modelErrors = config.modelErrorCount ?? 0;
  const toolTimeouts = config.toolTimeoutCount ?? 0;
  const modelBackpressure = config.modelBackpressureCount ?? 0;
  const toolBackpressure = config.toolBackpressureCount ?? 0;
  const inflightModelCalls = config.inflightModelCalls ?? 0;
  const queuedModelCalls = config.queuedModelCalls ?? 0;
  const inflightToolCalls = config.inflightToolCalls ?? 0;
  const queuedToolCalls = config.queuedToolCalls ?? 0;
  const maxInflightModelCalls = config.maxInflightModelCalls ?? 0;
  const maxInflightTools = config.maxInflightTools ?? 0;
  const execQueueDepth = config.execQueueDepth ?? 0;
  const requestCount = config.requestCount ?? 0;
  const requestSuccessCount = config.requestSuccessCount ?? 0;
  const requestErrorCount = config.requestErrorCount ?? 0;
  const requestRejectCount = config.requestRejectCount ?? 0;
  const requestCancelCount = config.requestCancelCount ?? 0;
  const requestSamples = config.requestSamples ?? 0;
  const queuedMsP50 = config.queuedMsP50 ?? 0;
  const queuedMsP95 = config.queuedMsP95 ?? 0;
  const modelMsP50 = config.modelMsP50 ?? 0;
  const modelMsP95 = config.modelMsP95 ?? 0;
  const toolMsP50 = config.toolMsP50 ?? 0;
  const toolMsP95 = config.toolMsP95 ?? 0;
  const totalMsP50 = config.totalMsP50 ?? 0;
  const totalMsP95 = config.totalMsP95 ?? 0;
  const lastRequestStatus = config.lastRequestStatus ?? "";
  const lastRequestQueuedMs = config.lastRequestQueuedMs ?? 0;
  const lastRequestModelMs = config.lastRequestModelMs ?? 0;
  const lastRequestToolMs = config.lastRequestToolMs ?? 0;
  const lastRequestTotalMs = config.lastRequestTotalMs ?? 0;

  const retrySummary = modelRetryBackoffMs > 0
    ? `retry ${modelRetries} (${modelRetryBackoffMs}ms) · err ${modelErrors}`
    : `retry ${modelRetries} · err ${modelErrors}`;

  const lines = [
    `req ${requestCount} · ok ${requestSuccessCount} · err ${requestErrorCount} · rej ${requestRejectCount} · cancel ${requestCancelCount}`,
    `tool avg ${toolLatencyMs}ms · wait ${permissionWaitMs}/${reviewWaitMs}ms · n=${toolLatencySamples}`,
    `timeouts p/r/t ${permissionTimeouts}/${reviewTimeouts}/${toolTimeouts}`,
    `${retrySummary} · bp ${modelBackpressure}/${toolBackpressure}`,
    compact
      ? `budget m ${inflightModelCalls}/${maxInflightModelCalls}+${queuedModelCalls}/${execQueueDepth} · t ${inflightToolCalls}/${maxInflightTools}+${queuedToolCalls}/${execQueueDepth}`
      : `budget m ${inflightModelCalls}/${maxInflightModelCalls}+${queuedModelCalls}/${execQueueDepth} · t ${inflightToolCalls}/${maxInflightTools}+${queuedToolCalls}/${execQueueDepth}`,
    requestSamples > 0
      ? `lat p50 q/m/t ${queuedMsP50}/${modelMsP50}/${toolMsP50}ms · total ${totalMsP50}ms`
      : "lat p50 q/m/t 0/0/0ms · total 0ms",
    requestSamples > 0
      ? `lat p95 q/m/t ${queuedMsP95}/${modelMsP95}/${toolMsP95}ms · total ${totalMsP95}ms`
      : "lat p95 q/m/t 0/0/0ms · total 0ms",
    lastRequestStatus
      ? `last ${lastRequestStatus} q/m/t/total ${lastRequestQueuedMs}/${lastRequestModelMs}/${lastRequestToolMs}/${lastRequestTotalMs}ms`
      : "",
  ];

  return lines.filter(Boolean).slice(0, lineLimit);
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
  const { colors, settings } = useSettingsContext();
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
  const diagnosticsLines = buildDiagnosticsLines(
    config,
    limits.diagnosticsLineLimit,
    limits.compact,
  );
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

      {settings.showDiagnostics ? (
        <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
          <Text bold color={colors.triforce}>Diagnostics</Text>
          {diagnosticsLines.map((line) => (
            <Text key={line} dimColor>{line}</Text>
          ))}
        </Box>
      ) : null}

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
