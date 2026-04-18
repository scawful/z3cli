/**
 * Root application component.
 *
 * Owns: backend lifecycle, settings state, settings panel open/close.
 * Delegates: command dispatch → commands/index.ts, rendering → child components.
 *
 * Architecture:
 *   useBackend  — IPC with Python process
 *   useSettings — persistent UI toggles
 *   SettingsContext.Provider — makes settings available to all children
 *   dispatchCommand — command table, shared by interactive + batch handlers
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";
import { ScrollView, type ScrollViewRef } from "ink-scroll-view";
import { useBackend } from "../hooks/useBackend.js";
import { useSettings } from "../hooks/useSettings.js";
import { SettingsContext } from "../contexts/SettingsContext.js";
import { dispatchCommand, executeShell, normalizeSessions } from "../commands/index.js";
import type { SessionInfo } from "../commands/index.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { StatusBar } from "./StatusBar.js";
import { PromptInput } from "./PromptInput.js";
import { TitleBar } from "./TitleBar.js";
import { SettingsPanel } from "./SettingsPanel.js";
import { HelpPanel } from "./HelpPanel.js";
import { ModelManagerPanel } from "./ModelManagerPanel.js";
import { PermissionDialog } from "./PermissionDialog.js";
import { ContextPanel } from "./ContextPanel.js";
import { TranscriptScroll } from "./TranscriptScroll.js";
import { ToolReviewDialog } from "./ToolReviewDialog.js";
import { BackendErrorBanner } from "./BackendErrorBanner.js";
import { shouldShowBackendErrorBanner } from "../utils/backendHealth.js";
import { symbols, getThemeColors } from "../theme/index.js";
import type { AttachmentMeta, ConstructRef } from "../ipc/protocol.js";
import type { CommandContext } from "../commands/index.js";
import { useTerminalSize } from "../hooks/useTerminalWidth.js";
import { useMouseScroll } from "../hooks/useMouseScroll.js";
import { shouldSuppressWelcome } from "../utils/cliArgs.js";
import {
  computeContextPanelLayout,
  computeTranscriptViewportHeight,
  groupMessages,
  resolveTranscriptHotkey,
  shouldShowKeyboardLegend,
} from "../utils/transcript.js";
import { estimateContextWindow } from "../utils/models.js";

// ---------------------------------------------------------------------------
// Loading screen
// ---------------------------------------------------------------------------

function ConnectingSpinner({ theme }: { theme: string }): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.thinking);
  const colors = getThemeColors(theme);
  return (
    <Box padding={1} gap={1}>
      <Text color={colors.triforce}>{spinner}</Text>
      <Text dimColor>Connecting to z3cli backend...</Text>
    </Box>
  );
}

export interface AppSummarySnapshot {
  model: string;
  sessionPath: string;
  messageCount: number;
  promptTokens: number;
  completionTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
}

interface AppProps {
  pythonPath: string;
  backendArgs: string[];
  batchCommands: string[];
  onSummaryUpdate?: (snapshot: AppSummarySnapshot) => void;
}

export type PromptSubmission =
  | { kind: "ignore" }
  | { kind: "shell"; command: string }
  | { kind: "message"; text: string; attachments: AttachmentMeta[]; constructRefs: ConstructRef[] }
  | { kind: "command"; cmd: string; args: string[] };

export interface StreamingCancelHotkeyState {
  isStreaming: boolean;
  rawModeSupported: boolean;
  settingsOpen: boolean;
  helpOpen: boolean;
  modelManagerOpen: boolean;
  hasPendingPermission: boolean;
  hasPendingReview: boolean;
}

export function classifyPromptSubmission(
  text: string,
  attachments: AttachmentMeta[] = [],
  constructRefs: ConstructRef[] = [],
): PromptSubmission {
  const trimmed = text.trim();
  if (!trimmed && attachments.length === 0 && constructRefs.length === 0) {
    return { kind: "ignore" };
  }
  if (!trimmed) {
    return { kind: "message", text: "", attachments, constructRefs };
  }
  if (trimmed.startsWith("!")) {
    return { kind: "shell", command: trimmed.slice(1).trim() };
  }
  if (!trimmed.startsWith("/")) {
    return { kind: "message", text: trimmed, attachments, constructRefs };
  }
  const [cmd, ...args] = trimmed.split(/\s+/) as [string, ...string[]];
  return { kind: "command", cmd, args };
}

export function shouldEnableStreamingCancelHotkeys(
  state: StreamingCancelHotkeyState,
): boolean {
  return (
    state.rawModeSupported
    && state.isStreaming
    && !state.settingsOpen
    && !state.helpOpen
    && !state.modelManagerOpen
    && !state.hasPendingPermission
    && !state.hasPendingReview
  );
}

export function App({ pythonPath, backendArgs, batchCommands, onSummaryUpdate }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const ranBatch = useRef(false);
  const transcriptScrollRef = useRef<ScrollViewRef | null>(null);
  const contextScrollRef = useRef<ScrollViewRef | null>(null);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function KeyboardLegend({ colors }: { colors: any }): React.ReactElement {
    return (
      <Box width="100%" paddingX={1} marginTop={0}>
        <Text dimColor>
          <Text color={colors.triforce}>[Ctrl+P]</Text> Palette {symbols.dot}{" "}
          <Text color={colors.triforce}>[Tab]</Text> Complete {symbols.dot}{" "}
          <Text color={colors.triforce}>[Shift+Tab]</Text> Mode {symbols.dot}{" "}
          <Text color={colors.triforce}>[Ctrl+R]</Text> Summary {symbols.dot}{" "}
          <Text color={colors.triforce}>[Alt+M/R/T/A]</Text> Filters {symbols.dot}{" "}
          <Text color={colors.triforce}>[PgUp/PgDn/Mouse]</Text> Scroll
        </Text>
      </Box>
    );
  }

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [modelManagerOpen, setModelManagerOpen] = useState(false);
  const [pickerSessions, setPickerSessions] = useState<SessionInfo[] | null>(null);
  const [recentSessions, setRecentSessions] = useState<SessionInfo[]>([]);
  const [draftFiles, setDraftFiles] = useState<AttachmentMeta[]>([]);
  const [draftConstructRefs, setDraftConstructRefs] = useState<ConstructRef[]>([]);
  const [dismissedErrorCount, setDismissedErrorCount] = useState<number | null>(null);
  const {
    settings,
    toggleSetting,
    setSetting,
    resetSettings,
    cycleMode,
    cycleTheme,
    cycleThinkingMode,
    cycleThinkingDetail,
  } = useSettings();
  const { width: terminalWidth, rows: terminalRows } = useTerminalSize();
  const showKeyboardLegend = shouldShowKeyboardLegend(terminalRows);

  const {
    config,
    messages,
    streamingContent, streamingThinking,
    isStreaming, activeToolCall,
    promptTokens, completionTokens,
    cacheCreationTokens, cacheReadTokens,
    error,
    pendingPermission,
    pendingReview,
    subagents,
    sendMessage, sendCommand,
    addSystemMessage, replaceMessages, replaceSubagents, updateConfig,
    cancelStream,
    approveTool, approveToolForSession, denyTool, denyToolForSession,
    acceptToolReview, rejectToolReview,
  } = useBackend(pythonPath, backendArgs);

  const backendErrorVisible = shouldShowBackendErrorBanner({
    requestErrorCount: config?.requestErrorCount,
    requestSuccessCount: config?.requestSuccessCount,
    lastRequestStatus: config?.lastRequestStatus,
    dismissedErrorCount,
  });
  const transcriptViewportHeight = computeTranscriptViewportHeight(
    terminalRows,
    showKeyboardLegend,
    backendErrorVisible,
  );

  // Build the command context once per render cycle so dispatchCommand
  // always sees current state without stale closures.
  const commandCtx = useMemo((): CommandContext => ({
    config,
    settings,
    addSystemMessage,
    replaceMessages,
    replaceSubagents,
    updateConfig,
    sendCommand,
    sendMessage,
    setSetting,
    resetSettings,
    openSettings: () => setSettingsOpen(true),
    openHelp: () => setHelpOpen(true),
    openModelManager: () => setModelManagerOpen(true),
    openSessionPicker: (sessions: SessionInfo[]) => setPickerSessions(sessions),
    exit,
  }), [config, settings, addSystemMessage, replaceMessages, replaceSubagents, updateConfig, sendCommand, sendMessage, setSetting, resetSettings, exit]);

  const handleSubmit = useCallback((
    text: string,
    attachments: AttachmentMeta[] = [],
    constructRefs: ConstructRef[] = [],
  ) => {
    const submission = classifyPromptSubmission(text, attachments, constructRefs);
    if (submission.kind === "ignore") return;
    if (submission.kind === "shell") {
      void executeShell(submission.command, commandCtx);
      return;
    }
    if (submission.kind === "message") {
      void sendMessage(submission.text, submission.attachments, submission.constructRefs).catch(() => undefined);
      return;
    }
    void dispatchCommand(submission.cmd, submission.args, commandCtx);
  }, [sendMessage, commandCtx]);

  // Escape cancels streaming; Shift+Tab cycles UI mode.
  useInput(
    (input, key) => {
      const ctrlChar = key.ctrl ? input.toLowerCase() : "";
      if (key.escape || ctrlChar === "c" || input === "\x03") cancelStream();
    },
    {
      isActive: shouldEnableStreamingCancelHotkeys({
        isStreaming,
        rawModeSupported: Boolean(process.stdin.isTTY),
        settingsOpen,
        helpOpen,
        modelManagerOpen,
        hasPendingPermission: Boolean(pendingPermission),
        hasPendingReview: Boolean(pendingReview),
      }),
    },
  );

  // Transcript hotkeys toggle reasoning collapse plus the message/reason/tool/subagent filters.
  useInput(
    (input, key) => {
      const action = resolveTranscriptHotkey(input, key);
      if (action) {
        toggleSetting(action);
      }
    },
    {
      isActive:
        Boolean(process.stdin.isTTY)
        && !settingsOpen
        && !helpOpen
        && !modelManagerOpen
        && !pendingPermission
        && !pendingReview,
    },
  );

  // Mouse-wheel scrolls the transcript. Disabled while a modal is open so
  // dialog input keeps default terminal behavior.
  useMouseScroll(transcriptScrollRef, {
    isActive:
      !settingsOpen
      && !helpOpen
      && !modelManagerOpen
      && !pendingPermission
      && !pendingReview,
    sidePanelScrollRef: computeContextPanelLayout(terminalWidth, settingsOpen).visible
      ? contextScrollRef
      : undefined,
  });

  // Escape dismisses the backend error banner when it's the most prominent
  // surface. Only active when nothing else (streaming, modals) owns Escape.
  useInput(
    (_input, key) => {
      if (key.escape) {
        setDismissedErrorCount(config?.requestErrorCount ?? 0);
      }
    },
    {
      isActive:
        Boolean(process.stdin.isTTY)
        && backendErrorVisible
        && !isStreaming
        && !settingsOpen
        && !helpOpen
        && !modelManagerOpen
        && !pendingPermission
        && !pendingReview,
    },
  );

  // Admin mode auto-approves any pending tool permission request.
  useEffect(() => {
    if (pendingPermission && settings.uiMode === "admin") {
      void approveTool();
    }
  }, [pendingPermission, settings.uiMode, approveTool]);

  // Keep the exit-banner snapshot fresh so index.tsx can render it after unmount.
  useEffect(() => {
    if (!onSummaryUpdate || !config) return;
    onSummaryUpdate({
      model: config.activeModel,
      sessionPath: config.sessionPath,
      messageCount: Math.max(
        config.sessionMessages ?? 0,
        messages.filter((m) => m.role === "user").length,
      ),
      promptTokens,
      completionTokens,
      cacheReadTokens,
      cacheCreationTokens,
    });
  }, [
    onSummaryUpdate, config, messages,
    promptTokens, completionTokens, cacheReadTokens, cacheCreationTokens,
  ]);

  // Context usage estimate (0–100) based on current transcript content.
  const { contextPercent, contextWindow } = useMemo(() => {
    if (!config) {
      return { contextPercent: 0, contextWindow: 0 };
    }
    const estimatedTokens = messages.reduce((sum, message) =>
      message.role === "system" ? sum : sum + Math.ceil(message.content.length / 4), 0);
    const window = estimateContextWindow(config.activeModel, config.models);
    const percent = window > 0 ? Math.min(100, Math.round((estimatedTokens / window) * 100)) : 0;
    return { contextPercent: percent, contextWindow: window };
  }, [config, messages]);

  const groupedMessages = useMemo(() => groupMessages(messages), [messages]);
  const contextPanelLayout = useMemo(
    () => computeContextPanelLayout(terminalWidth, settingsOpen),
    [terminalWidth, settingsOpen],
  );
  const showContextPanel = contextPanelLayout.visible;
  const contextPanelWidth = contextPanelLayout.width;

  useEffect(() => {
    if (!showContextPanel) return;
    contextScrollRef.current?.remeasure();
  }, [transcriptViewportHeight, showContextPanel]);

  useEffect(() => {
    if (!config) return;
    let cancelled = false;
    void sendCommand("/sessions", []).then((result) => {
      if (cancelled) return;
      const raw = (result as { sessions?: Array<Record<string, unknown>> } | null)?.sessions ?? [];
      setRecentSessions(normalizeSessions(raw));
    }).catch(() => {
      if (!cancelled) setRecentSessions([]);
    });
    return () => {
      cancelled = true;
    };
  }, [config?.sessionPath, sendCommand]);

  // Run batch commands once after config arrives.
  useEffect(() => {
    if (!config || ranBatch.current || batchCommands.length === 0) return;
    ranBatch.current = true;
    const pause = () => new Promise<void>((r) => setTimeout(r, 60));
    void (async () => {
      for (const line of batchCommands) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (!trimmed.startsWith("/")) {
          await sendMessage(trimmed).catch(() => undefined);
        } else {
          const [cmd, ...args] = trimmed.split(/\s+/) as [string, ...string[]];
          await dispatchCommand(cmd, args, commandCtx);
        }
        await pause();
      }
    })();
  }, [batchCommands, config, commandCtx, sendMessage]);

  if (!config) return <ConnectingSpinner theme={settings.theme} />;

  const themeColors = getThemeColors(settings.theme);
  const suppressWelcome = shouldSuppressWelcome(batchCommands);

  return (
    <SettingsContext.Provider value={{
      settings,
      colors: themeColors,
      config,
      execCommand: (cmd, args) => { void dispatchCommand(cmd, args, commandCtx); },
      toggleSetting,
      setSetting,
      resetSettings,
      cycleMode,
      cycleTheme,
      cycleThinkingMode,
      cycleThinkingDetail,
    }}>
      <Box flexDirection="column" width="100%">
        <TitleBar
          version={config.version}
          backend={config.backend}
          model={config.activeModel}
          mode={config.mode}
          contextPercent={contextPercent}
          romPath={config.romPath}
          broadcastModels={config.broadcastModels}
        />

        {backendErrorVisible ? <BackendErrorBanner config={config} /> : null}

        <Box flexDirection={showContextPanel ? "row" : "column"} width="100%" gap={1}>
          <Box flexDirection="column" flexGrow={1} minWidth={0}>
            <TranscriptScroll
              scrollRef={transcriptScrollRef}
              viewportHeight={transcriptViewportHeight}
              groupedMessages={groupedMessages}
              themeColors={themeColors}
              config={config}
              messagesLength={messages.length}
              isStreaming={isStreaming}
              streamingContent={streamingContent}
              streamingThinking={streamingThinking}
              activeToolCall={activeToolCall}
              subagents={subagents}
              error={error}
              suppressWelcome={suppressWelcome}
            />
          </Box>

          {showContextPanel ? (
            <Box
              height={transcriptViewportHeight}
              width={contextPanelWidth}
              flexShrink={0}
              flexDirection="column"
            >
              <ScrollView ref={contextScrollRef} width="100%" flexGrow={1}>
                <Box key="context-rail" flexDirection="column" width="100%">
                  <ContextPanel
                    config={config}
                    contextPercent={contextPercent}
                    contextWindow={contextWindow}
                    promptTokens={promptTokens}
                    completionTokens={completionTokens}
                    userMessageCount={Math.max(
                      config.sessionMessages ?? 0,
                      messages.filter((m) => m.role === "user").length,
                    )}
                    recentSessions={recentSessions}
                    draftFiles={draftFiles}
                    draftConstructRefs={draftConstructRefs}
                    width={contextPanelWidth}
                    viewportHeight={transcriptViewportHeight}
                  />
                </Box>
              </ScrollView>
            </Box>
          ) : null}
        </Box>

        {settingsOpen
          ? <SettingsPanel onClose={() => setSettingsOpen(false)} />
          : null}

        {helpOpen
          ? <HelpPanel onClose={() => setHelpOpen(false)} />
          : null}

        {modelManagerOpen
          ? <ModelManagerPanel config={config} onClose={() => setModelManagerOpen(false)} />
          : null}

        {pendingPermission && settings.uiMode !== "admin" ? (
          <PermissionDialog
            name={pendingPermission.name}
            server={pendingPermission.server}
            workspace={config.workspace}
            arguments={pendingPermission.arguments}
            reason={pendingPermission.reason}
            onApproveOnce={() => void approveTool()}
            onApproveSession={() => void approveToolForSession()}
            onDenyOnce={() => void denyTool()}
            onDenySession={() => void denyToolForSession()}
          />
        ) : pendingReview ? (
          <ToolReviewDialog
            name={pendingReview.name}
            server={pendingReview.server}
            summary={pendingReview.summary}
            paths={pendingReview.paths}
            diffLines={pendingReview.diffLines}
            omitted={pendingReview.omitted}
            verificationCommands={pendingReview.verificationCommands}
            onAccept={() => void acceptToolReview()}
            onReject={() => void rejectToolReview()}
          />
        ) : null}

          <PromptInput
            mode={config.mode}
            model={config.activeModel}
            models={config.models}
            loadedModels={config.loadedModels}
            workspace={config.workspace}
            backend={config.backend}
            focusFile={config.focusFile}
          hasStickyPermissions={Object.keys(config.permissionRules ?? {}).length > 0}
          recentSessions={recentSessions}
          disabled={isStreaming || settingsOpen || helpOpen || modelManagerOpen || Boolean(pendingPermission) || Boolean(pendingReview)}
          isStreaming={isStreaming}
          hint={settingsOpen ? `settings open ${symbols.dot} Esc to close` : helpOpen ? `Book of Mudora open ${symbols.dot} Esc to close` : modelManagerOpen ? `oracle register open ${symbols.dot} Esc to close` : undefined}
          sessions={pickerSessions}
          onCycleMode={cycleMode}
          onOpenModelManager={() => setModelManagerOpen(true)}
          onSessionClose={() => setPickerSessions(null)}
          onDraftFilesChange={setDraftFiles}
          onDraftConstructRefsChange={setDraftConstructRefs}
          onSubmit={handleSubmit}
          transcriptScrollRef={transcriptScrollRef}
          sidePanelScrollRef={showContextPanel ? contextScrollRef : undefined}
        />

        <StatusBar
          model={config.activeModel}
          serverCount={config.servers.length}
          toolCount={config.toolCount}
          messageCount={Math.max(
            config.sessionMessages ?? 0,
            messages.filter((m) => m.role === "user").length,
          )}
          promptTokens={promptTokens}
          completionTokens={completionTokens}
          cacheReadTokens={cacheReadTokens}
          cacheCreationTokens={cacheCreationTokens}
          isStreaming={isStreaming}
          workspace={config.workspace}
          warningCount={config.warnings.length}
          toolsEnabled={config.toolsEnabled}
          focusFile={config.focusFile}
        />

        {showKeyboardLegend ? <KeyboardLegend colors={themeColors} /> : null}
      </Box>
    </SettingsContext.Provider>
  );
}
