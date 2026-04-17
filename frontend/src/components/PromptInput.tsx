/**
 * Text input with slash-command autocomplete, command history,
 * and interactive model/mode pickers.
 */

import React, { useEffect, useMemo, useState } from "react";
import { Box, Text, useInput } from "ink";
import type { ScrollViewRef } from "ink-scroll-view";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import * as nodePath from "node:path";
import { createInterface } from "node:readline";
import { promisify } from "node:util";
import { symbols, modelColor, modelSymbol, getThemeColors, uiModeColor } from "../theme/index.js";
import type { AttachmentMeta, AttachmentReference, ModelInfo } from "../ipc/protocol.js";
import type { SessionInfo } from "../commands/index.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { basename, shortenPath } from "../utils/path.js";
import { modelPickerDescription } from "../utils/models.js";
import {
  activeFileMention,
  extractMentionedFiles,
  filterFiles,
  filterPalette,
  sessionDate,
  sessionMatches,
  sessionSlug,
} from "../utils/prompt.js";
import type { PaletteEntry } from "../utils/prompt.js";

const execFileAsync = promisify(execFile);

// ---------------------------------------------------------------------------
// Command registry
// ---------------------------------------------------------------------------

interface CommandDef {
  name: string;
  args: string; // "" = none, "<...>" = required, "[...]" = optional
  description: string;
}

const COMMANDS: CommandDef[] = [
  { name: "/help",      args: "",              description: "Show available commands" },
  { name: "/backend",   args: "[name]",        description: "Show or set backend" },
  { name: "/backends",  args: "",              description: "List available backends" },
  { name: "/backend-status", args: "",         description: "Show backend status" },
  { name: "/model",     args: "<name>",        description: "Switch active model" },
  { name: "/orchestrator", args: "[name|auto]", description: "Show or set orchestrator planner" },
  { name: "/mode",      args: "<name>",        description: "Set routing mode" },
  { name: "/models",    args: "",              description: "List Zelda models" },
  { name: "/modes",     args: "",              description: "List routing modes" },
  { name: "/status",    args: "",              description: "Connection and state info" },
  { name: "/servers",   args: "",              description: "Tool server info" },
  { name: "/tools",     args: "<on|off>",      description: "Toggle tool use" },
  { name: "/tools-write", args: "<on|off>",    description: "Toggle tool write access" },
  { name: "/verify-hooks", args: "<on|off>",   description: "Toggle automatic verification" },
  { name: "/permissions", args: "[clear]",     description: "Show or clear sticky tool rules" },
  { name: "/specialist", args: "<name>",       description: "Switch to a specialist in manual mode" },
  { name: "/route",     args: "<prompt>",      description: "Preview routing" },
  { name: "/broadcast", args: "<a,b,c>",       description: "Set broadcast models" },
  { name: "/load",      args: "[name]",        description: "Load model in LM Studio" },
  { name: "/loaded",    args: "",              description: "List loaded API models" },
  { name: "/workspace", args: "<path>",        description: "Change workspace" },
  { name: "/rom",       args: "<path|none>",   description: "Change ROM target" },
  { name: "/reset",     args: "[model|all]",   description: "Clear history" },
  { name: "/stats",     args: "",              description: "Session statistics" },
  { name: "/save",      args: "",              description: "Show session file path" },
  { name: "/sessions",  args: "",              description: "List saved sessions" },
  { name: "/resume",    args: "<name>",        description: "Resume a saved session" },
  { name: "/compact",   args: "[model]",       description: "Compress history (lossy)" },
  { name: "/shell",     args: "[command]",     description: "Run a persistent shell command" },
  { name: "/shell-reset", args: "",            description: "Reset the persistent shell session" },
  { name: "/shell-log", args: "[count]",       description: "Show recent shell commands" },
  { name: "/settings",  args: "[key on|off]",  description: "Open UI settings panel" },
  { name: "/focus",     args: "<path|clear>",  description: "Load file into system prompt" },
  { name: "/exit",      args: "",              description: "Quit z3cli" },
];

// ---------------------------------------------------------------------------
// Routing modes
// ---------------------------------------------------------------------------

interface ModeDef {
  name: string;
  description: string;
}

const MODES: ModeDef[] = [
  { name: "manual",       description: "Route to active model only" },
  { name: "oracle",       description: "Portfolio router" },
  { name: "orchestrator", description: "Cloud planner delegates to specialists" },
  { name: "broadcast",    description: "Fan out to multiple models" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type SelectorKind = null | "model" | "mode" | "session" | "palette";

// ---------------------------------------------------------------------------
// Word boundary helpers
// ---------------------------------------------------------------------------

function wordBoundaryLeft(text: string, pos: number): number {
  let i = pos - 1;
  while (i >= 0 && text[i] === " ") i--;
  while (i >= 0 && text[i] !== " ") i--;
  return i + 1;
}

function wordBoundaryRight(text: string, pos: number): number {
  let i = pos;
  while (i < text.length && text[i] !== " ") i++;
  while (i < text.length && text[i] === " ") i++;
  return i;
}

// ---------------------------------------------------------------------------
// Session display helpers
// ---------------------------------------------------------------------------

const SESSION_MAX_VISIBLE = 12;
const FILE_MAX_VISIBLE = 10;
const PALETTE_MAX_VISIBLE = 12;
const EXIT_CONFIRM_WINDOW_MS = 1500;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PromptInputProps {
  mode: string;
  model: string;
  models: ModelInfo[];
  workspace: string;
  backend?: string;
  focusFile?: string;
  hasStickyPermissions?: boolean;
  recentSessions?: SessionInfo[];
  disabled: boolean;
  isStreaming?: boolean;
  hint?: string;
  sessions?: SessionInfo[] | null;
  paletteTrigger?: number;
  onCycleMode?: () => void;
  onSessionClose?: () => void;
  onDraftFilesChange?: (files: AttachmentMeta[]) => void;
  onSubmit: (text: string, attachments?: AttachmentReference[]) => void;
  transcriptScrollRef?: React.RefObject<ScrollViewRef | null>;
  sidePanelScrollRef?: React.RefObject<ScrollViewRef | null>;
}

export function PromptInput({
  mode,
  model,
  models,
  workspace,
  backend,
  focusFile,
  hasStickyPermissions,
  recentSessions = [],
  disabled,
  isStreaming,
  hint,
  sessions,
  paletteTrigger = 0,
  onCycleMode,
  onSessionClose,
  onDraftFilesChange,
  onSubmit,
  transcriptScrollRef,
  sidePanelScrollRef,
}: PromptInputProps): React.ReactElement {
  const { settings, colors } = useSettingsContext();
  const rawModeSupported = Boolean(process.stdin.isTTY);
  const [value, setValue] = useState("");
  const [cursor, setCursor] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [selectedCompletion, setSelectedCompletion] = useState(0);

  // Interactive picker state
  const [selector, setSelector] = useState<SelectorKind>(null);
  const [selectorIndex, setSelectorIndex] = useState(0);
  const [sessionScrollOffset, setSessionScrollOffset] = useState(0);
  const [sessionFilter, setSessionFilter] = useState("");
  const [workspaceFiles, setWorkspaceFiles] = useState<string[]>([]);
  const [fileIndex, setFileIndex] = useState(0);
  const [fileScrollOffset, setFileScrollOffset] = useState(0);
  const [fileLoadError, setFileLoadError] = useState("");
  const [paletteFilter, setPaletteFilter] = useState("");
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [paletteScrollOffset, setPaletteScrollOffset] = useState(0);
  const [exitArmedUntil, setExitArmedUntil] = useState(0);
  const [exitMessage, setExitMessage] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<string[]>([]);
  const [attachmentMeta, setAttachmentMeta] = useState<Record<string, AttachmentMeta>>({});

  // Auto-open session picker when sessions list arrives from a command
  useEffect(() => {
    if (sessions && sessions.length > 0) {
      setSelector("session");
      setSelectorIndex(0);
      setSessionScrollOffset(0);
      setSessionFilter("");
    }
  }, [sessions]);

  const sessionList = sessions ?? recentSessions;
  const filteredSessions = useMemo(() => {
    const filter = sessionFilter.trim().toLowerCase();
    if (!filter) return sessionList;
    return sessionList.filter((session) => sessionMatches(session, filter));
  }, [sessionFilter, sessionList]);

  useEffect(() => {
    if (selector !== "session") return;
    setSelectorIndex((idx) => Math.max(0, Math.min(idx, filteredSessions.length - 1)));
    setSessionScrollOffset((offset) => {
      const nextIndex = Math.max(0, Math.min(selectorIndex, filteredSessions.length - 1));
      if (nextIndex < offset) return nextIndex;
      if (nextIndex >= offset + SESSION_MAX_VISIBLE) {
        return Math.max(0, nextIndex - SESSION_MAX_VISIBLE + 1);
      }
      return offset;
    });
  }, [filteredSessions.length, selector, selectorIndex]);

  useEffect(() => {
    let cancelled = false;

    async function loadWorkspaceFiles() {
      if (!workspace) {
        setWorkspaceFiles([]);
        setFileLoadError("");
        return;
      }

      try {
        const { stdout } = await execFileAsync("rg", ["--files"], {
          cwd: workspace,
          maxBuffer: 16 * 1024 * 1024,
        });
        if (cancelled) return;
        setWorkspaceFiles(stdout.split("\n").filter(Boolean));
        setFileLoadError("");
        return;
      } catch {
        try {
          const { stdout } = await execFileAsync("find", [".", "-type", "f"], {
            cwd: workspace,
            maxBuffer: 16 * 1024 * 1024,
          });
          if (cancelled) return;
          setWorkspaceFiles(
            stdout
              .split("\n")
              .map((line) => line.replace(/^\.\//, ""))
              .filter(Boolean),
          );
          setFileLoadError("");
        } catch (error) {
          if (cancelled) return;
          setWorkspaceFiles([]);
          setFileLoadError(error instanceof Error ? error.message : String(error));
        }
      }
    }

    void loadWorkspaceFiles();
    return () => {
      cancelled = true;
    };
  }, [workspace]);

  // ---- Autocomplete ----

  const completions = useMemo(() => {
    if (!value.startsWith("/") || value.includes(" ")) return [];
    const prefix = value.toLowerCase();
    return COMMANDS.filter((cmd) => cmd.name.startsWith(prefix));
  }, [value]);

  const showCompletions = completions.length > 0 && value.length >= 1;

  // Scrolling window for long completion list
  const maxVisible = 10;
  const compStart = Math.max(
    0,
    Math.min(selectedCompletion - 4, completions.length - maxVisible),
  );
  const compEnd = Math.min(completions.length, compStart + maxVisible);
  const visibleCompletions = completions.slice(compStart, compEnd);
  const mentionedFiles = useMemo(
    () => extractMentionedFiles(value, workspaceFiles),
    [value, workspaceFiles],
  );
  const draftFilePaths = useMemo(() => {
    const seen = new Set<string>();
    const merged: string[] = [];
    for (const filePath of [...attachedFiles, ...mentionedFiles]) {
      if (!filePath || seen.has(filePath)) continue;
      seen.add(filePath);
      merged.push(filePath);
    }
    return merged;
  }, [attachedFiles, mentionedFiles]);
  const draftFiles = useMemo(
    () => draftFilePaths.map((filePath) => attachmentMeta[filePath] ?? {
      path: filePath,
      lines: 0,
      chars: 0,
    }),
    [attachmentMeta, draftFilePaths],
  );
  const fileMention = useMemo(() => activeFileMention(value, cursor), [value, cursor]);
  const fileMatches = useMemo(() => {
    if (selector || !fileMention) return [];
    return filterFiles(workspaceFiles, fileMention.query);
  }, [fileMention, selector, workspaceFiles]);
  const showFilePicker = selector === null && fileMention !== null;
  const paletteEntries = useMemo((): PaletteEntry[] => {
    const entries: PaletteEntry[] = [
      { key: "cmd-help", label: "Help", description: "Show command help", command: "/help", aliases: "help commands" },
      { key: "cmd-sessions", label: "Sessions", description: "Browse saved sessions", command: "/sessions", aliases: "resume sessions history" },
      { key: "cmd-resume", label: "Resume Session Picker", description: "Open session search", command: "/resume", aliases: "resume session search" },
      { key: "cmd-model", label: "Model Picker", description: "Choose the active model", command: "/model", aliases: "model switch" },
      { key: "cmd-orchestrator", label: "Orchestrator", description: "Show or set the cloud planner", command: "/orchestrator", aliases: "orchestrator planner cloud" },
      { key: "cmd-mode", label: "Mode Picker", description: "Choose routing mode", command: "/mode", aliases: "route mode" },
      { key: "cmd-status", label: "Status", description: "Show current runtime state", command: "/status", aliases: "status info" },
      { key: "cmd-settings", label: "Settings", description: "Open UI settings", command: "/settings", aliases: "settings ui" },
      { key: "cmd-permissions", label: "Permissions", description: "Show sticky tool rules", command: "/permissions", aliases: "permissions rules tools" },
    ];
    if (focusFile) {
      entries.push({
        key: "focus-clear",
        label: "Clear Focus File",
        description: basename(focusFile),
        command: "/focus clear",
        aliases: `focus clear ${focusFile}`,
      });
    }
    if (hasStickyPermissions) {
      entries.push({
        key: "permissions-clear",
        label: "Clear Sticky Permissions",
        description: "Remove saved allow/deny rules",
        command: "/permissions clear",
        aliases: "clear permissions sticky",
      });
    }
    for (const backendName of ["studio", "llamacpp"]) {
      entries.push({
        key: `backend-${backendName}`,
        label: `Backend ${backendName}`,
        description: backend === backendName ? "current backend" : "switch backend",
        command: `/backend ${backendName}`,
        aliases: `backend ${backendName}`,
      });
    }
    for (const modelInfo of models) {
      const description = modelPickerDescription(modelInfo);
      entries.push({
        key: `model-${modelInfo.name}`,
        label: `Model ${modelInfo.name}`,
        description,
        command: `/model ${modelInfo.name}`,
        aliases: `model ${modelInfo.name} ${description}`,
      });
    }
    for (const modeInfo of MODES) {
      entries.push({
        key: `mode-${modeInfo.name}`,
        label: `Mode ${modeInfo.name}`,
        description: modeInfo.description,
        command: `/mode ${modeInfo.name}`,
        aliases: `mode ${modeInfo.name} ${modeInfo.description}`,
      });
    }
    for (const session of recentSessions.slice(0, 30)) {
      entries.push({
        key: `session-${session.name}`,
        label: `Resume ${sessionSlug(session.name)}`,
        description: `${session.activeModel} · ${session.preview || session.workspace || session.name}`,
        command: `/resume ${session.name}`,
        aliases: `resume ${session.name} ${session.activeModel} ${session.preview} ${session.workspace}`,
      });
    }
    return entries;
  }, [backend, focusFile, hasStickyPermissions, model, models, recentSessions]);
  const filteredPalette = useMemo(
    () => filterPalette(paletteEntries, paletteFilter),
    [paletteEntries, paletteFilter],
  );

  useEffect(() => {
    if (!showFilePicker) {
      setFileIndex(0);
      setFileScrollOffset(0);
      return;
    }
    setFileIndex((idx) => Math.max(0, Math.min(idx, fileMatches.length - 1)));
    setFileScrollOffset((offset) => {
      const nextIndex = Math.max(0, Math.min(fileIndex, fileMatches.length - 1));
      if (nextIndex < offset) return nextIndex;
      if (nextIndex >= offset + FILE_MAX_VISIBLE) {
        return Math.max(0, nextIndex - FILE_MAX_VISIBLE + 1);
      }
      return offset;
    });
  }, [fileIndex, fileMatches.length, showFilePicker]);

  useEffect(() => {
    if (selector !== "palette") return;
    setPaletteIndex((idx) => Math.max(0, Math.min(idx, filteredPalette.length - 1)));
    setPaletteScrollOffset((offset) => {
      const nextIndex = Math.max(0, Math.min(paletteIndex, filteredPalette.length - 1));
      if (nextIndex < offset) return nextIndex;
      if (nextIndex >= offset + PALETTE_MAX_VISIBLE) {
        return Math.max(0, nextIndex - PALETTE_MAX_VISIBLE + 1);
      }
      return offset;
    });
  }, [filteredPalette.length, paletteIndex, selector]);

  useEffect(() => {
    onDraftFilesChange?.(draftFiles);
  }, [draftFiles, onDraftFilesChange]);

  useEffect(() => {
    let cancelled = false;
    const missing = draftFilePaths.filter((filePath) => !attachmentMeta[filePath]);
    if (missing.length === 0) return undefined;
    void Promise.all(
      missing.map(async (filePath) => {
        const resolved = nodePath.isAbsolute(filePath)
          ? filePath
          : nodePath.join(workspace, filePath);
        try {
          const content = await readFile(resolved, "utf8");
          return {
            path: filePath,
            lines: content.split("\n").length,
            chars: content.length,
          };
        } catch {
          return {
            path: filePath,
            lines: 0,
            chars: 0,
          };
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      setAttachmentMeta((current) => {
        const next = { ...current };
        for (const result of results) {
          if ("chars" in result) {
            next[result.path] = result;
            continue;
          }
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [attachmentMeta, draftFilePaths, workspace]);

  useEffect(() => {
    if (!paletteTrigger || disabled || !rawModeSupported) return;
    openPalette();
  }, [disabled, paletteTrigger, rawModeSupported]);

  useEffect(() => {
    if (!exitArmedUntil) {
      if (exitMessage) setExitMessage("");
      return;
    }
    const remaining = exitArmedUntil - Date.now();
    if (remaining <= 0) {
      setExitArmedUntil(0);
      if (exitMessage) setExitMessage("");
      return;
    }
    const timer = setTimeout(() => {
      setExitArmedUntil(0);
      setExitMessage("");
    }, remaining);
    return () => clearTimeout(timer);
  }, [exitArmedUntil, exitMessage]);

  // ---- Helpers ----

  function clearInput() {
    setValue("");
    setCursor(0);
    setHistoryIndex(-1);
    setSelectedCompletion(0);
  }

  function clearAttachedFiles() {
    setAttachedFiles([]);
  }

  function clearExitPrompt() {
    setExitArmedUntil(0);
    setExitMessage("");
  }

  function openModelPicker() {
    clearExitPrompt();
    setSelector("model");
    setSelectorIndex(Math.max(0, models.findIndex((m) => m.name === model)));
    clearInput();
  }

  function openModePicker() {
    clearExitPrompt();
    setSelector("mode");
    setSelectorIndex(Math.max(0, MODES.findIndex((m) => m.name === mode)));
    clearInput();
  }

  function openPalette() {
    clearExitPrompt();
    setSelector("palette");
    setPaletteFilter("");
    setPaletteIndex(0);
    setPaletteScrollOffset(0);
    clearInput();
  }

  function buildSubmittedMessage(text: string): string {
    return text.trimEnd();
  }

  function submittedAttachments(text: string): AttachmentReference[] {
    if (text.trimStart().startsWith("/")) {
      return [];
    }
    return draftFiles.map((file) => ({ path: file.path }));
  }

  function submitAndRecord(text: string) {
    clearExitPrompt();
    onSubmit(buildSubmittedMessage(text), submittedAttachments(text));
    setHistory((h) => [text, ...h]);
    clearInput();
    clearAttachedFiles();
  }

  function attachDraftFile(filePath: string) {
    if (!fileMention) return;
    clearExitPrompt();
    const before = value.slice(0, fileMention.start);
    const after = value.slice(fileMention.end).replace(/^\s+/, "");
    const nextValue = `${before}${after}`.replace(/\s{3,}/g, "  ");
    const nextCursor = before.length;
    setValue(nextValue);
    setCursor(nextCursor);
    setFileIndex(0);
    setFileScrollOffset(0);
    setAttachedFiles((current) => (
      current.includes(filePath) ? current : [...current, filePath]
    ));
  }

  function popAttachedFile(): boolean {
    if (attachedFiles.length === 0) return false;
    clearExitPrompt();
    setAttachedFiles((current) => current.slice(0, -1));
    return true;
  }

  function armExit(message: string) {
    setExitArmedUntil(Date.now() + EXIT_CONFIRM_WINDOW_MS);
    setExitMessage(message);
  }

  function clearInteractiveState(): boolean {
    let cleared = false;
    if (selector) {
      const current = selector;
      setSelector(null);
      if (current === "session") onSessionClose?.();
      cleared = true;
    }
    if (value || historyIndex !== -1 || selectedCompletion !== 0) {
      clearInput();
      cleared = true;
    }
    if (attachedFiles.length > 0) {
      clearAttachedFiles();
      cleared = true;
    }
    return cleared;
  }

  function handleInterrupt() {
    const now = Date.now();
    const cleared = clearInteractiveState();
    if (!cleared && exitArmedUntil > now) {
      process.exit(0);
      return;
    }
    armExit(cleared ? "Cleared. Ctrl+C again to exit" : "Press Ctrl+C again to exit");
  }

  useEffect(() => {
    if (rawModeSupported) {
      return undefined;
    }
    const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
    rl.on("line", (line) => {
      if (!disabled && line.trim()) {
        onSubmit(line);
      }
    });
    return () => rl.close();
  }, [disabled, onSubmit, rawModeSupported]);

  // ---- Input handling ----

  useInput(
    (input, key) => {
      const ctrlChar = key.ctrl ? input.toLowerCase() : "";
      const isCtrl = (char: string, raw: string): boolean =>
        ctrlChar === char || input === raw;
      const ctrlC = isCtrl("c", "\x03");
      const isEnter = key.return || input === "\r" || input === "\n";

      if (!ctrlC && exitArmedUntil) {
        clearExitPrompt();
      }

      // Escape: cancel selector
      if (key.escape) {
        if (selector) {
          setSelector(null);
          clearInput();
          if (selector === "session") onSessionClose?.();
        }
        return;
      }

      if (isCtrl("p", "\x10")) {
        openPalette();
        return;
      }

      if (key.shift && key.tab) {
        onCycleMode?.();
        return;
      }

      if (!selector && !showFilePicker) {
        if (key.ctrl && (key.pageUp || key.pageDown) && sidePanelScrollRef?.current) {
          const r = sidePanelScrollRef.current;
          const h = r.getViewportHeight() || 1;
          r.scrollBy(key.pageUp ? -h : h);
          return;
        }
        if (key.pageUp || key.pageDown) {
          const r = transcriptScrollRef?.current;
          if (r) {
            const h = r.getViewportHeight() || 1;
            r.scrollBy(key.pageUp ? -h : h);
            return;
          }
        }
      }

      // ── Session selector ──
      if (selector === "session") {
        const list = filteredSessions;
        if (key.upArrow) {
          setSelectorIndex((i) => {
            const next = Math.max(0, i - 1);
            setSessionScrollOffset((off) => Math.min(off, next));
            return next;
          });
          return;
        }
        if (key.downArrow) {
          setSelectorIndex((i) => {
            const next = list.length > 0 ? Math.min(list.length - 1, i + 1) : 0;
            setSessionScrollOffset((off) => Math.max(off, next - SESSION_MAX_VISIBLE + 1));
            return next;
          });
          return;
        }
        if (isEnter) {
          const sel = list[selectorIndex];
          if (sel) submitAndRecord(`/resume ${sel.name}`);
          setSelector(null);
          onSessionClose?.();
          return;
        }
        if (key.backspace || key.delete) {
          setSessionFilter((value) => value.slice(0, -1));
          setSelectorIndex(0);
          setSessionScrollOffset(0);
          return;
        }
        if (input && !key.ctrl && !key.meta) {
          setSessionFilter((value) => value + input);
          setSelectorIndex(0);
          setSessionScrollOffset(0);
          return;
        }
        if (ctrlC) {
          handleInterrupt();
          return;
        }
        return;
      }

      if (selector === "palette") {
        if (key.upArrow) {
          setPaletteIndex((i) => {
            const next = Math.max(0, i - 1);
            setPaletteScrollOffset((off) => Math.min(off, next));
            return next;
          });
          return;
        }
        if (key.downArrow) {
          setPaletteIndex((i) => {
            const next = filteredPalette.length > 0 ? Math.min(filteredPalette.length - 1, i + 1) : 0;
            setPaletteScrollOffset((off) => Math.max(off, next - PALETTE_MAX_VISIBLE + 1));
            return next;
          });
          return;
        }
        if (isEnter) {
          const selected = filteredPalette[paletteIndex];
          if (selected) submitAndRecord(selected.command);
          setSelector(null);
          return;
        }
        if (key.backspace || key.delete) {
          setPaletteFilter((current) => current.slice(0, -1));
          setPaletteIndex(0);
          setPaletteScrollOffset(0);
          return;
        }
        if (input && !key.ctrl && !key.meta) {
          setPaletteFilter((current) => current + input);
          setPaletteIndex(0);
          setPaletteScrollOffset(0);
          return;
        }
        if (ctrlC) {
          handleInterrupt();
          return;
        }
        return;
      }

      // ── Model / mode selector ──
      if (selector) {
        const items = selector === "model" ? models : MODES;

        if (key.upArrow) {
          setSelectorIndex((i) => Math.max(0, i - 1));
          return;
        }
        if (key.downArrow) {
          setSelectorIndex((i) => Math.min(items.length - 1, i + 1));
          return;
        }
        if (isEnter) {
          if (selector === "model") {
            const sel = models[selectorIndex];
            if (sel) submitAndRecord(`/model ${sel.name}`);
          } else {
            const sel = MODES[selectorIndex];
            if (sel) submitAndRecord(`/mode ${sel.name}`);
          }
          setSelector(null);
          return;
        }
        if (ctrlC) {
          handleInterrupt();
          return;
        }
        return; // swallow all other keys in selector mode
      }

      if (showFilePicker) {
        if (key.upArrow) {
          setFileIndex((i) => {
            const next = Math.max(0, i - 1);
            setFileScrollOffset((off) => Math.min(off, next));
            return next;
          });
          return;
        }
        if (key.downArrow) {
          setFileIndex((i) => {
            const next = fileMatches.length > 0 ? Math.min(fileMatches.length - 1, i + 1) : 0;
            setFileScrollOffset((off) => Math.max(off, next - FILE_MAX_VISIBLE + 1));
            return next;
          });
          return;
        }
        if ((key.tab || isEnter) && fileMatches[fileIndex]) {
          attachDraftFile(fileMatches[fileIndex]!);
          return;
        }
      }

      // ── Tab: fill selected completion ──
      if (key.tab && showCompletions) {
        const cmd = completions[selectedCompletion % completions.length];
        if (cmd) {
          if (cmd.name === "/model") { openModelPicker(); return; }
          if (cmd.name === "/mode") { openModePicker(); return; }
          const fill = cmd.args.startsWith("<") ? cmd.name + " " : cmd.name;
          setValue(fill);
          setCursor(fill.length);
          setSelectedCompletion(0);
        }
        return;
      }

      // ── Enter ──
      if (isEnter) {
        // Autocomplete is showing — act on highlighted item
        if (showCompletions && completions.length > 0) {
          const cmd = completions[selectedCompletion % completions.length];
          if (cmd) {
            if (cmd.name === "/model") { openModelPicker(); return; }
            if (cmd.name === "/mode") { openModePicker(); return; }
            // No args or optional args → execute immediately
            if (!cmd.args || cmd.args.startsWith("[")) {
              submitAndRecord(cmd.name);
              return;
            }
            // Required args → fill and let user type args
            const fill = cmd.name + " ";
            setValue(fill);
            setCursor(fill.length);
            setSelectedCompletion(0);
            return;
          }
        }

        // Direct submit (no autocomplete visible)
        const trimmed = value.trim();
        if (!trimmed && attachedFiles.length === 0) return;
        // Intercept bare /model and /mode
        if (trimmed.toLowerCase() === "/model") { openModelPicker(); return; }
        if (trimmed.toLowerCase() === "/mode") { openModePicker(); return; }
        submitAndRecord(value);
        return;
      }

      // ── Backspace ──
      if (key.backspace || key.delete) {
        if (cursor === 0 && !value && popAttachedFile()) {
          return;
        }
        if (cursor > 0) {
          setValue((v) => v.slice(0, cursor - 1) + v.slice(cursor));
          setCursor((c) => c - 1);
          setSelectedCompletion(0);
        }
        return;
      }

      // ── Left / Right ──
      if (key.leftArrow) { setCursor((c) => Math.max(0, c - 1)); return; }
      if (key.rightArrow) { setCursor((c) => Math.min(value.length, c + 1)); return; }

      // ── Up / Down ──
      if (key.upArrow) {
        if (showCompletions) {
          setSelectedCompletion((s) => Math.max(0, s - 1));
        } else if (history.length > 0) {
          const idx = Math.min(historyIndex + 1, history.length - 1);
          setHistoryIndex(idx);
          const v = history[idx]!;
          setValue(v);
          setCursor(v.length);
        }
        return;
      }
      if (key.downArrow) {
        if (showCompletions) {
          setSelectedCompletion((s) => Math.min(completions.length - 1, s + 1));
        } else if (historyIndex > 0) {
          const idx = historyIndex - 1;
          setHistoryIndex(idx);
          const v = history[idx]!;
          setValue(v);
          setCursor(v.length);
        } else {
          setHistoryIndex(-1);
          setValue("");
          setCursor(0);
        }
        return;
      }

      // Ctrl+C
      if (ctrlC) {
        handleInterrupt();
        return;
      }
      // Ctrl+A / Ctrl+E
      if (isCtrl("a", "\x01")) { setCursor(0); return; }
      if (isCtrl("e", "\x05")) { setCursor(value.length); return; }

      // Ctrl+U — clear to beginning of line
      if (isCtrl("u", "\x15")) {
        setValue((v) => v.slice(cursor));
        setCursor(0);
        return;
      }
      // Ctrl+K — kill to end of line
      if (isCtrl("k", "\x0B")) {
        setValue((v) => v.slice(0, cursor));
        return;
      }
      // Ctrl+W — delete word before cursor
      if (isCtrl("w", "\x17")) {
        const boundary = wordBoundaryLeft(value, cursor);
        setValue((v) => v.slice(0, boundary) + v.slice(cursor));
        setCursor(boundary);
        return;
      }
      // Ctrl+D — exit when empty, forward delete otherwise
      if (isCtrl("d", "\x04")) {
        if (!value) { process.exit(0); return; }
        setValue((v) => v.slice(0, cursor) + v.slice(cursor + 1));
        return;
      }

      // Alt+Left / Alt+B — word left
      if ((key.meta && key.leftArrow) || (key.meta && input === "b")) {
        setCursor(wordBoundaryLeft(value, cursor));
        return;
      }
      // Alt+Right / Alt+F — word right
      if ((key.meta && key.rightArrow) || (key.meta && input === "f")) {
        setCursor(wordBoundaryRight(value, cursor));
        return;
      }
      // Alt+Backspace — delete word backward
      if (key.meta && (key.backspace || key.delete)) {
        const boundary = wordBoundaryLeft(value, cursor);
        setValue((v) => v.slice(0, boundary) + v.slice(cursor));
        setCursor(boundary);
        return;
      }

      // Regular character
      if (input && !key.ctrl && !key.meta) {
        setValue((v) => v.slice(0, cursor) + input + v.slice(cursor));
        setCursor((c) => c + input.length);
        setSelectedCompletion(0);
      }
    },
    { isActive: !disabled && rawModeSupported },
  );

  // ---- Render ----

  const before = value.slice(0, cursor);
  const cursorChar = value[cursor] ?? " ";
  const after = value.slice(cursor + 1);

  // Session picker visible window
  const sesStart = sessionScrollOffset;
  const sesEnd = Math.min(filteredSessions.length, sesStart + SESSION_MAX_VISIBLE);
  const visibleSessions = filteredSessions.slice(sesStart, sesEnd);
  const fileStart = fileScrollOffset;
  const fileEnd = Math.min(fileMatches.length, fileStart + FILE_MAX_VISIBLE);
  const visibleFiles = fileMatches.slice(fileStart, fileEnd);
  const paletteStart = paletteScrollOffset;
  const paletteEnd = Math.min(filteredPalette.length, paletteStart + PALETTE_MAX_VISIBLE);
  const visiblePalette = filteredPalette.slice(paletteStart, paletteEnd);

  return (
    <Box flexDirection="column">
      {/* ── Session picker ── */}
      {selector === "session" ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} Resume session</Text>
            <Text dimColor>({filteredSessions.length}/{sessionList.length})</Text>
          </Box>
          <Box marginBottom={1}>
            <Text dimColor>filter: </Text>
            <Text color={colors.text}>{sessionFilter || "(all sessions)"}</Text>
          </Box>
          {sesStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {sesStart} more above</Text>
          ) : null}
          {filteredSessions.length === 0 ? (
            <Box paddingY={1}>
              <Text dimColor>  no sessions match that filter</Text>
            </Box>
          ) : null}
          {visibleSessions.map((s, vi) => {
            const i = vi + sesStart;
            const isSelected = i === selectorIndex;
            const slug = sessionSlug(s.name).padEnd(18);
            const date = sessionDate(s.updated || s.started);
            const mc = modelColor(s.activeModel, colors);
            return (
              <Box key={s.name} flexDirection="column" paddingY={0}>
                <Box gap={1}>
                  <Text color={isSelected ? colors.triforce : colors.dim}>
                    {isSelected ? symbols.arrowRight : " "}
                  </Text>
                  <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                    {slug}
                  </Text>
                  <Text dimColor>{date.padEnd(12)}</Text>
                  <Text color={isSelected ? mc : colors.muted} bold={isSelected}>
                    {s.activeModel}
                  </Text>
                  <Text dimColor>{s.messages}m {s.toolCalls}t</Text>
                </Box>
                {isSelected && (s.workspace || s.preview) ? (
                  <Box paddingLeft={2} flexDirection="column">
                    {s.workspace ? (
                      <Text dimColor italic>{shortenPath(s.workspace)}</Text>
                    ) : null}
                    {s.preview ? (
                      <Text dimColor>"{s.preview}"</Text>
                    ) : null}
                  </Box>
                ) : null}
              </Box>
            );
          })}
          {sesEnd < filteredSessions.length ? (
            <Text dimColor>  {symbols.triforceSmall} {filteredSessions.length - sesEnd} more below</Text>
          ) : null}
          <Box marginTop={1}>
            <Text dimColor>↑↓ navigate {symbols.dot} Enter resume {symbols.dot} Esc cancel</Text>
          </Box>
        </Box>

      /* ── Model picker ── */
      ) : selector === "model" ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} Select model</Text>
          </Box>
          {models.map((m, i) => {
            const isSelected = i === selectorIndex;
            const description = modelPickerDescription(m);
            return (
              <Box key={m.name} gap={1}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text color={modelColor(m.name, colors)}>{modelSymbol(m.name)}</Text>
                <Text
                  color={isSelected ? modelColor(m.name, colors) : colors.muted}
                  bold={isSelected}
                >
                  {m.name.padEnd(18)}
                </Text>
                {description ? <Text dimColor>{description}</Text> : null}
                {m.loaded ? <Text color={colors.success}> {symbols.dot}</Text> : null}
                {m.toolsEnabled ? <Text color={colors.tool}> {symbols.sword}</Text> : null}
                {m.name === model ? (
                  <Text color={colors.triforce}> {symbols.triforceSmall}</Text>
                ) : null}
              </Box>
            );
          })}
          <Box marginTop={1}>
            <Text dimColor>↑↓ navigate {symbols.dot} Enter select {symbols.dot} Esc cancel</Text>
          </Box>
        </Box>

      /* ── Mode picker ── */
      ) : selector === "mode" ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} Select routing mode</Text>
          </Box>
          {MODES.map((m, i) => {
            const isSelected = i === selectorIndex;
            return (
              <Box key={m.name} gap={1}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text
                  color={isSelected ? colors.accent : colors.muted}
                  bold={isSelected}
                >
                  {m.name.padEnd(14)}
                </Text>
                <Text dimColor>{m.description}</Text>
                {m.name === mode ? (
                  <Text color={colors.triforce}> {symbols.triforceSmall}</Text>
                ) : null}
              </Box>
            );
          })}
          <Box marginTop={1}>
            <Text dimColor>↑↓ navigate {symbols.dot} Enter select {symbols.dot} Esc cancel</Text>
          </Box>
        </Box>

      /* ── Command palette ── */
      ) : selector === "palette" ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} Command palette</Text>
          </Box>
          <Box marginBottom={1}>
            <Text dimColor>filter: </Text>
            <Text color={colors.text}>{paletteFilter || "(all actions)"}</Text>
          </Box>
          {paletteStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {paletteStart} more above</Text>
          ) : null}
          {visiblePalette.length === 0 ? (
            <Box paddingY={1}>
              <Text dimColor>  no actions match that filter</Text>
            </Box>
          ) : null}
          {visiblePalette.map((entry, vi) => {
            const i = vi + paletteStart;
            const isSelected = i === paletteIndex;
            return (
              <Box key={entry.key} gap={1}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                  {entry.label.padEnd(20)}
                </Text>
                <Text color={isSelected ? colors.accent : colors.muted}>{entry.description}</Text>
              </Box>
            );
          })}
          {paletteEnd < filteredPalette.length ? (
            <Text dimColor>  {symbols.triforceSmall} {filteredPalette.length - paletteEnd} more below</Text>
          ) : null}
          <Box marginTop={1}>
            <Text dimColor>type to filter {symbols.dot} ↑↓ navigate {symbols.dot} Enter run {symbols.dot} Esc cancel</Text>
          </Box>
        </Box>

      /* ── File autocomplete ── */
      ) : showFilePicker ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} File reference</Text>
            <Text color={colors.text}>@{fileMention?.query || ""}</Text>
          </Box>
          <Box marginBottom={1}>
            <Text dimColor>workspace: </Text>
            <Text dimColor>{shortenPath(workspace)}</Text>
          </Box>
          {fileLoadError ? (
            <Text color={colors.warning}>  file index unavailable: {fileLoadError}</Text>
          ) : null}
          {fileStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {fileStart} more above</Text>
          ) : null}
          {visibleFiles.length === 0 && !fileLoadError ? (
            <Box paddingY={1}>
              <Text dimColor>  no files match that query</Text>
            </Box>
          ) : null}
          {visibleFiles.map((path, vi) => {
            const i = vi + fileStart;
            const isSelected = i === fileIndex;
            const meta = attachmentMeta[path];
            const isAttached = attachedFiles.includes(path);
            return (
              <Box key={path} gap={1}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                  {basename(path)}
                </Text>
                <Text dimColor>{path}</Text>
                {meta && meta.lines > 0 ? <Text dimColor>{meta.lines}L</Text> : null}
                {isAttached ? <Text color={colors.success}>attached</Text> : null}
              </Box>
            );
          })}
          {fileEnd < fileMatches.length ? (
            <Text dimColor>  {symbols.triforceSmall} {fileMatches.length - fileEnd} more below</Text>
          ) : null}
          <Box marginTop={1}>
            <Text dimColor>type to refine {symbols.dot} ↑↓ navigate {symbols.dot} Tab/Enter attach</Text>
          </Box>
        </Box>

      /* ── Command autocomplete ── */
      ) : showCompletions ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          {compStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {compStart} more above</Text>
          ) : null}
          {visibleCompletions.map((cmd, vi) => {
            const i = vi + compStart;
            const isSelected = i === selectedCompletion;
            return (
              <Box key={cmd.name} gap={1}>
                <Text
                  color={isSelected ? colors.triforce : colors.dim}
                  bold={isSelected}
                >
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text
                  color={isSelected ? colors.text : colors.muted}
                  bold={isSelected}
                >
                  {cmd.name.padEnd(14)}
                </Text>
                {cmd.args ? <Text color={isSelected ? colors.accent : colors.muted}>{cmd.args.padEnd(14)}</Text> : <Text>{"".padEnd(14)}</Text>}
                <Text dimColor>{cmd.description}</Text>
              </Box>
            );
          })}
          {compEnd < completions.length ? (
            <Text dimColor>  {symbols.triforceSmall} {completions.length - compEnd} more below</Text>
          ) : null}
        </Box>
      ) : null}

      {draftFiles.length > 0 && !selector ? (
        <Box paddingLeft={2} flexDirection="column">
          <Box gap={1} flexWrap="wrap">
            <Text dimColor>attached</Text>
            {draftFiles.slice(0, 8).map((file) => (
              <Text key={file.path} color={colors.nayru}>
                @{file.path}{file.lines > 0 ? ` ${file.lines}L` : ""}{file.chars > 0 ? ` ${file.chars}C` : ""}
              </Text>
            ))}
          </Box>
          {attachedFiles.length > 0 ? (
            <Text dimColor>Backspace on an empty prompt removes the last @file</Text>
          ) : null}
        </Box>
      ) : null}

      {/* ── Input line ── */}
      <Box width="100%" borderStyle="round" borderColor={uiModeColor(settings.uiMode, colors)} paddingX={1}>
        <Box gap={1}>
          <Text color={modelColor(model, colors)} bold>
            {modelSymbol(model)}
          </Text>
          <Text color={modelColor(model, colors)} bold>{model}</Text>
        </Box>
        <Text color={colors.triforce} bold>
          {" "}
          {symbols.arrowRight}{" "}
        </Text>
        {selector ? (
          <Text dimColor>selecting {selector}...</Text>
        ) : hint ? (
          <Text dimColor>{hint}</Text>
        ) : isStreaming ? (
          <Text dimColor>streaming... press <Text bold color={colors.text}>Esc</Text> to cancel</Text>
        ) : (
          <Text>
            {before}
            <Text inverse>{cursorChar}</Text>
            {after}
          </Text>
        )}
      </Box>

      {exitMessage ? (
        <Box paddingLeft={2}>
          <Text color={colors.warning}>{exitMessage}</Text>
        </Box>
      ) : null}
    </Box>
  );
}
