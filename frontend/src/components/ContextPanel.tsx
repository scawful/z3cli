import React from "react";
import { Box, Text } from "ink";
import type { AppConfig, AttachmentMeta } from "../ipc/protocol.js";
import type { SessionInfo } from "../commands/index.js";
import { getThemeColors, heartBar, modelColor, modelSymbol, symbols, formatTokens } from "../theme/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { basename, shortenPath } from "../utils/path.js";

interface ContextPanelProps {
  config: AppConfig;
  contextPercent: number;
  contextWindow: number;
  promptTokens: number;
  completionTokens: number;
  userMessageCount: number;
  recentSessions: SessionInfo[];
  draftFiles: AttachmentMeta[];
}

function sessionName(name: string): string {
  return name.replace(/^\d{4}-\d{2}-\d{2}_\d{6}(?:_\d+)?_?/, "") || name;
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
}: ContextPanelProps): React.ReactElement {
  const { colors } = useSettingsContext();
  const totalTokens = promptTokens + completionTokens;
  const tokenDisplay = formatTokens(totalTokens, colors);
  const hearts = heartBar(contextPercent, 10, colors);
  const rules = config.permissionRules ?? {};
  const allowCount = Object.values(rules).filter(Boolean).length;
  const denyCount = Object.values(rules).filter((value) => !value).length;
  const cancelCount = config.cancelCount ?? 0;
  const restartCount = config.backendRestartCount ?? 0;
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
  const modelQueueHighwater = config.modelQueueHighwater ?? 0;
  const toolQueueHighwater = config.toolQueueHighwater ?? 0;
  const modelRetryMax = config.modelRetryMax ?? 0;
  const modelRetryBaseMs = config.modelRetryBaseMs ?? 0;
  const toolExecTimeoutS = config.toolExecTimeoutS ?? 0;
  const maxInflightModelCalls = config.maxInflightModelCalls ?? 0;
  const maxInflightTools = config.maxInflightTools ?? 0;
  const execQueueDepth = config.execQueueDepth ?? 0;
  const requestCount = config.requestCount ?? 0;
  const requestSuccessCount = config.requestSuccessCount ?? 0;
  const requestErrorCount = config.requestErrorCount ?? 0;
  const requestRejectCount = config.requestRejectCount ?? 0;
  const requestCancelCount = config.requestCancelCount ?? 0;
  const spanCount = config.spanCount ?? 0;
  const lastRequestId = config.lastRequestId ?? "";
  const lastSpanId = config.lastSpanId ?? "";
  const lastToolCallId = config.lastToolCallId ?? "";
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

  return (
    <Box width={36} flexDirection="column" gap={1}>
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
        ) : (
          <Text dimColor>no focus file</Text>
        )}
        <Text dimColor>
          shell {config.shellActive ? "active" : "idle"} · {shortenPath(config.shellCwd ?? config.workspace)}
        </Text>
        <Text dimColor>session {basename(config.sessionPath) || "(none)"}</Text>
        <Text dimColor>{config.servers.length} servers · {config.toolCount} tools</Text>
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Status & Session</Text>
        <Text dimColor>{userMessageCount} user turns</Text>
        <Text dimColor>session token spend</Text>
        <Box gap={1}>
          <Text color={tokenDisplay.color}>{tokenDisplay.text || "◆ 0"}</Text>
        </Box>
        {contextWindow > 0 ? (
          <>
            <Text dimColor>context estimate</Text>
            <Box gap={1}>
              <Text color={hearts.color}>{hearts.display} {contextPercent}%</Text>
              <Text dimColor>of current window</Text>
            </Box>
          </>
        ) : null}
        <Text dimColor>{config.sessionToolCalls ?? 0} tool calls</Text>
        <Text dimColor>rules {allowCount} allow · {denyCount} deny</Text>
        <Text dimColor>verify {config.verifyHooks === false ? "off" : "on"}</Text>
        <Text dimColor>cancel {cancelCount} · restart {restartCount}</Text>
        <Text dimColor>tool avg {toolLatencyMs}ms · n={toolLatencySamples}</Text>
        <Text dimColor>wait p/r {permissionWaitMs}ms/{reviewWaitMs}ms</Text>
        <Text dimColor>timeouts p/r {permissionTimeouts}/{reviewTimeouts}</Text>
        <Text dimColor>model retry {modelRetries} · errors {modelErrors}</Text>
        <Text dimColor>retry backoff {modelRetryBackoffMs}ms · max {modelRetryMax}</Text>
        <Text dimColor>retry base {modelRetryBaseMs}ms · tool timeout {toolExecTimeoutS}s</Text>
        <Text dimColor>tool timeouts {toolTimeouts}</Text>
        <Text dimColor>budget model {inflightModelCalls}/{maxInflightModelCalls} · queue {queuedModelCalls}/{execQueueDepth}</Text>
        <Text dimColor>budget tools {inflightToolCalls}/{maxInflightTools} · queue {queuedToolCalls}/{execQueueDepth}</Text>
        <Text dimColor>backpressure m/t {modelBackpressure}/{toolBackpressure}</Text>
        <Text dimColor>queue highwater m/t {modelQueueHighwater}/{toolQueueHighwater}</Text>
        <Text dimColor>requests {requestCount} · ok {requestSuccessCount} · err {requestErrorCount} · rej {requestRejectCount} · cancel {requestCancelCount}</Text>
        <Text dimColor>spans {spanCount}</Text>
        <Text dimColor>latency p50 q/m/t {queuedMsP50}/{modelMsP50}/{toolMsP50}ms</Text>
        <Text dimColor>latency p95 q/m/t {queuedMsP95}/{modelMsP95}/{toolMsP95}ms</Text>
        <Text dimColor>latency p50/p95 total {totalMsP50}/{totalMsP95}ms (n={requestSamples})</Text>
        {lastRequestStatus ? (
          <Text dimColor>last {lastRequestStatus} q/m/t/total {lastRequestQueuedMs}/{lastRequestModelMs}/{lastRequestToolMs}/{lastRequestTotalMs}ms</Text>
        ) : null}
        {lastRequestId ? <Text dimColor>last req {lastRequestId}</Text> : null}
        {lastSpanId ? <Text dimColor>last span {lastSpanId}</Text> : null}
        {lastToolCallId ? <Text dimColor>last tool call {lastToolCallId}</Text> : null}
      </Box>

      <Box borderStyle="double" borderColor={colors.border} paddingX={1} flexDirection="column">
        <Text bold color={colors.triforce}>Inventory (@files)</Text>
        {draftFiles.length === 0 ? (
          <Text dimColor>none</Text>
        ) : (
          draftFiles.slice(0, 6).map((file) => (
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
        <Text bold color={colors.triforce}>Quest Log (Recent)</Text>
        {recentSessions.length === 0 ? (
          <Text dimColor>no saved sessions</Text>
        ) : (
          recentSessions.slice(0, 5).map((session) => (
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
