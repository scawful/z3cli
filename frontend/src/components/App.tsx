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
import { Box, Static, Text, useApp, useInput } from "ink";
import { useBackend } from "../hooks/useBackend.js";
import { useSettings } from "../hooks/useSettings.js";
import { SettingsContext } from "../contexts/SettingsContext.js";
import { dispatchCommand, executeShell } from "../commands/index.js";
import { useAnimatedFrame } from "../hooks/useAnimatedFrame.js";
import { MessageBubble } from "./MessageBubble.js";
import { StreamingMessage } from "./StreamingMessage.js";
import { StatusBar } from "./StatusBar.js";
import { PromptInput } from "./PromptInput.js";
import { WelcomeBanner } from "./WelcomeBanner.js";
import { TitleBar } from "./TitleBar.js";
import { SettingsPanel } from "./SettingsPanel.js";
import { PermissionDialog } from "./PermissionDialog.js";
import { colors, symbols } from "../theme/index.js";
import type { Message } from "../ipc/protocol.js";
import type { CommandContext } from "../commands/index.js";

// ---------------------------------------------------------------------------
// Context window estimates (tokens) per model
// ---------------------------------------------------------------------------

const CONTEXT_WINDOWS: Record<string, number> = {
  din: 8192, nayru: 8192, farore: 8192,
  veran: 8192, majora: 8192, hylia: 8192,
  "oracle-tools": 8192,
  "switchhook-plan": 32768,
  "switchhook-act": 32768,
};

// ---------------------------------------------------------------------------
// Loading screen
// ---------------------------------------------------------------------------

function ConnectingSpinner(): React.ReactElement {
  const spinner = useAnimatedFrame(symbols.thinking);
  return (
    <Box padding={1} gap={1}>
      <Text color={colors.triforce}>{spinner}</Text>
      <Text dimColor>Connecting to z3cli backend...</Text>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

interface AppProps {
  pythonPath: string;
  backendArgs: string[];
  batchCommands: string[];
}

export function App({ pythonPath, backendArgs, batchCommands }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const ranBatch = useRef(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { settings, toggleSetting, setSetting, resetSettings, cycleMode } = useSettings();

  const {
    config,
    messages,
    streamingContent, streamingThinking,
    isStreaming, activeToolCall,
    promptTokens, completionTokens,
    error,
    pendingPermission,
    sendMessage, sendCommand,
    addSystemMessage, updateConfig,
    cancelStream,
    approveTool, denyTool,
  } = useBackend(pythonPath, backendArgs);

  // Build the command context once per render cycle so dispatchCommand
  // always sees current state without stale closures.
  const commandCtx = useMemo((): CommandContext => ({
    config,
    settings,
    addSystemMessage,
    updateConfig,
    sendCommand,
    sendMessage,
    setSetting,
    resetSettings,
    openSettings: () => setSettingsOpen(true),
    exit,
  }), [config, settings, addSystemMessage, updateConfig, sendCommand, sendMessage, setSetting, resetSettings, exit]);

  const handleSubmit = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (trimmed.startsWith("!")) {
      void executeShell(trimmed.slice(1).trim(), commandCtx);
      return;
    }
    if (!trimmed.startsWith("/")) {
      void sendMessage(trimmed);
      return;
    }
    const [cmd, ...args] = trimmed.split(/\s+/) as [string, ...string[]];
    void dispatchCommand(cmd, args, commandCtx);
  }, [sendMessage, commandCtx]);

  // Escape cancels streaming; Shift+Tab cycles UI mode.
  useInput(
    (input, key) => {
      if (key.escape || input === "\x03") cancelStream();
    },
    { isActive: isStreaming && !settingsOpen && Boolean(process.stdin.isTTY) },
  );

  useInput(
    (_, key) => {
      if (key.shift && key.tab) cycleMode();
    },
    { isActive: !settingsOpen && Boolean(process.stdin.isTTY) },
  );

  // Admin mode auto-approves any pending tool permission request.
  useEffect(() => {
    if (pendingPermission && settings.uiMode === "admin") {
      void approveTool();
    }
  }, [pendingPermission, settings.uiMode, approveTool]);

  // Context usage estimate (0–100).
  const contextPercent = useMemo(() => {
    if (!config) return 0;
    const tokens = messages.reduce((sum, m) =>
      m.role === "system" ? sum : sum + Math.ceil(m.content.length / 4), 0);
    const window = CONTEXT_WINDOWS[config.activeModel] ?? 8192;
    return Math.min(100, Math.round((tokens / window) * 100));
  }, [config, messages]);

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
          await sendMessage(trimmed);
        } else {
          const [cmd, ...args] = trimmed.split(/\s+/) as [string, ...string[]];
          await dispatchCommand(cmd, args, commandCtx);
        }
        await pause();
      }
    })();
  }, [batchCommands, config, commandCtx, sendMessage]);

  if (!config) return <ConnectingSpinner />;

  return (
    <SettingsContext.Provider value={{ settings, toggleSetting, setSetting, resetSettings, cycleMode }}>
      <Box flexDirection="column">
        <TitleBar
          version={config.version}
          backend={config.backend}
          model={config.activeModel}
          mode={config.mode}
          contextPercent={contextPercent}
          romPath={config.romPath}
          broadcastModels={config.broadcastModels}
        />

        <Static items={messages}>
          {(msg: Message, i: number) => (
            <Box key={`${msg.id}-${i}`} flexDirection="column">
              <MessageBubble message={msg} />
            </Box>
          )}
        </Static>

        {messages.length === 0 && !isStreaming
          ? <WelcomeBanner config={config} />
          : null}

        {isStreaming ? (
          <StreamingMessage
            content={streamingContent}
            thinkingContent={streamingThinking}
            activeToolCall={activeToolCall}
          />
        ) : null}

        {error ? (
          <Box borderStyle="round" borderColor={colors.error} paddingX={1} gap={1}>
            <Text color={colors.error}>{symbols.heart}</Text>
            <Text color={colors.error}>{error}</Text>
          </Box>
        ) : null}

        {settingsOpen
          ? <SettingsPanel onClose={() => setSettingsOpen(false)} />
          : null}

        {pendingPermission && settings.uiMode !== "admin" ? (
          <PermissionDialog
            name={pendingPermission.name}
            server={pendingPermission.server}
            arguments={pendingPermission.arguments}
            onApprove={() => void approveTool()}
            onDeny={() => void denyTool()}
          />
        ) : null}

        <PromptInput
          mode={config.mode}
          model={config.activeModel}
          models={config.models}
          disabled={isStreaming || settingsOpen}
          isStreaming={isStreaming}
          hint={settingsOpen ? `settings open ${symbols.dot} Esc to close` : undefined}
          onSubmit={handleSubmit}
        />

        <StatusBar
          model={config.activeModel}
          serverCount={config.servers.length}
          toolCount={config.toolCount}
          messageCount={messages.filter((m) => m.role === "user").length}
          promptTokens={promptTokens}
          completionTokens={completionTokens}
          isStreaming={isStreaming}
          workspace={config.workspace}
          warningCount={config.warnings.length}
          toolsEnabled={config.toolsEnabled}
          focusFile={config.focusFile}
        />
      </Box>
    </SettingsContext.Provider>
  );
}
