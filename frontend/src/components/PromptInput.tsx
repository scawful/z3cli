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
import type { AttachmentMeta, ConstructRef, LoadedModelInfo, ModelInfo } from "../ipc/protocol.js";
import type { SessionInfo } from "../commands/index.js";
import { buildBasePaletteEntries, COMMAND_CATALOG } from "../commands/catalog.js";
import { useSettingsContext } from "../contexts/SettingsContext.js";
import { basename, shortenPath } from "../utils/path.js";
import { describeLoadedModelRuntime, formatModelMemory, modelPickerDescription } from "../utils/models.js";
import { scrollTargetBy } from "../utils/scrolling.js";
import {
  activeConstructMention,
  activeFileMention,
  buildConstructCandidates,
  buildSpriteCatalogConstructCandidates,
  constructToken,
  extractMentionedConstructRefs,
  extractMentionedFiles,
  filterFiles,
  mergeConstructCandidates,
  filterPalette,
  searchConstructs,
  sessionDate,
  sessionMatches,
  sessionSlug,
} from "../utils/prompt.js";
import type { ConstructCandidate, PaletteEntry } from "../utils/prompt.js";

const execFileAsync = promisify(execFile);

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
const CONSTRUCT_MAX_VISIBLE = 10;
const PALETTE_MAX_VISIBLE = 12;
const EXIT_CONFIRM_WINDOW_MS = 1500;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PromptInputProps {
  mode: string;
  model: string;
  models: ModelInfo[];
  loadedModels?: LoadedModelInfo[];
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
  onOpenModelManager?: () => void;
  onSessionClose?: () => void;
  onDraftFilesChange?: (files: AttachmentMeta[]) => void;
  onDraftConstructRefsChange?: (refs: ConstructRef[]) => void;
  onSubmit: (text: string, attachments?: AttachmentMeta[], constructRefs?: ConstructRef[]) => void;
  transcriptScrollRef?: React.RefObject<ScrollViewRef | null>;
  sidePanelScrollRef?: React.RefObject<ScrollViewRef | null>;
}

export function PromptInput({
  mode,
  model,
  models,
  loadedModels = [],
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
  onOpenModelManager,
  onSessionClose,
  onDraftFilesChange,
  onDraftConstructRefsChange,
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
  const [attachedConstructRefs, setAttachedConstructRefs] = useState<ConstructRef[]>([]);
  const [attachmentMeta, setAttachmentMeta] = useState<Record<string, AttachmentMeta>>({});
  const [constructCandidates, setConstructCandidates] = useState<ConstructCandidate[]>([]);
  const [constructIndex, setConstructIndex] = useState(0);
  const [constructScrollOffset, setConstructScrollOffset] = useState(0);
  const [constructLoadError, setConstructLoadError] = useState("");

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

  useEffect(() => {
    let cancelled = false;

    async function loadConstructIndex() {
      if (!workspace) {
        setConstructCandidates([]);
        setConstructLoadError("");
        return;
      }
      const labelPath = [
        ...workspaceFiles.filter((filePath) => filePath.endsWith("oracle_resource_labels.json")),
        ...workspaceFiles.filter((filePath) => /resource_labels\.json$/i.test(filePath)),
      ][0];
      const spriteCatalogPath = workspaceFiles.find((filePath) => filePath.endsWith("sprite_catalog.md"));
      if (!labelPath && !spriteCatalogPath) {
        setConstructCandidates([]);
        setConstructLoadError("");
        return;
      }
      try {
        const [rawLabels, rawSpriteCatalog] = await Promise.all([
          labelPath ? readFile(nodePath.join(workspace, labelPath), "utf8") : Promise.resolve(""),
          spriteCatalogPath ? readFile(nodePath.join(workspace, spriteCatalogPath), "utf8") : Promise.resolve(""),
        ]);
        if (cancelled) return;
        const jsonCandidates = rawLabels ? buildConstructCandidates(JSON.parse(rawLabels)) : [];
        const catalogCandidates = rawSpriteCatalog
          ? buildSpriteCatalogConstructCandidates(rawSpriteCatalog)
          : [];
        setConstructCandidates(mergeConstructCandidates(jsonCandidates, catalogCandidates));
        setConstructLoadError("");
      } catch (error) {
        if (cancelled) return;
        setConstructCandidates([]);
        setConstructLoadError(error instanceof Error ? error.message : String(error));
      }
    }

    void loadConstructIndex();
    return () => {
      cancelled = true;
    };
  }, [workspace, workspaceFiles]);

  // ---- Autocomplete ----

  const completions = useMemo(() => {
    if (!value.startsWith("/") || value.includes(" ")) return [];
    const prefix = value.toLowerCase();
    return COMMAND_CATALOG.filter((cmd) => cmd.name.startsWith(prefix));
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
  const mentionedConstructRefs = useMemo(
    () => extractMentionedConstructRefs(value),
    [value],
  );
  const draftConstructRefs = useMemo(() => {
    const merged = new Map<string, ConstructRef>();
    for (const ref of [...attachedConstructRefs, ...mentionedConstructRefs]) {
      const key = `${ref.kind}:${(ref.id ?? ref.query).toLowerCase()}`;
      if (!merged.has(key)) {
        merged.set(key, ref);
      }
    }
    return [...merged.values()];
  }, [attachedConstructRefs, mentionedConstructRefs]);
  const constructMention = useMemo(() => activeConstructMention(value, cursor), [value, cursor]);
  const constructSearch = useMemo(() => {
    if (selector || !constructMention) {
      return {
        matches: [] as ConstructCandidate[],
        ambiguous: false,
        exactCount: 0,
        totalCount: 0,
      };
    }
    return searchConstructs(constructCandidates, constructMention.kind, constructMention.query);
  }, [constructCandidates, constructMention, selector]);
  const constructMatches = constructSearch.matches;
  const fileMention = useMemo(() => activeFileMention(value, cursor), [value, cursor]);
  const fileMatches = useMemo(() => {
    if (selector || !fileMention) return [];
    return filterFiles(workspaceFiles, fileMention.query);
  }, [fileMention, selector, workspaceFiles]);
  const showFilePicker = selector === null && fileMention !== null;
  const showConstructPicker = selector === null && constructMention !== null;
  const constructPickerTitle = constructSearch.ambiguous ? "Disambiguate reference" : "Game reference";
  const constructStatus = useMemo(() => {
    if (!constructMention || constructLoadError) return "";
    const query = constructMention.query.trim();
    if (!query) return `browse ${constructMention.kind} refs`;
    if (constructSearch.totalCount === 0) return "no project refs match that query";
    if (constructSearch.ambiguous) {
      const visibleCount = Math.min(constructSearch.totalCount, 200);
      return `${visibleCount} close matches - choose one or keep typing`;
    }
    if (constructSearch.exactCount === 1) return "exact project match - Enter attaches";
    if (constructSearch.totalCount === 1) return "best project match - Enter attaches";
    return `${Math.min(constructSearch.totalCount, 200)} matches - Enter attaches the highlighted ref`;
  }, [constructLoadError, constructMention, constructSearch]);
  const constructStatusColor = useMemo(() => {
    if (!constructMention || constructLoadError) return colors.dim;
    if (!constructMention.query.trim()) return colors.dim;
    if (constructSearch.totalCount === 0 || constructSearch.ambiguous) return colors.warning;
    return colors.success;
  }, [colors.dim, colors.success, colors.warning, constructLoadError, constructMention, constructSearch]);
  const paletteEntries = useMemo((): PaletteEntry[] => {
    const entries: PaletteEntry[] = buildBasePaletteEntries();
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
    for (const loadedModel of loadedModels) {
      const name = loadedModel.identifier || loadedModel.displayName || loadedModel.modelKey;
      const memory = formatModelMemory(loadedModel.sizeBytes);
      entries.push({
        key: `unload-${loadedModel.identifier || loadedModel.modelKey}`,
        label: `Unload ${name}`,
        description: [loadedModel.status, memory].filter(Boolean).join(" · ") || "Unload loaded model",
        command: `/unload ${loadedModel.identifier || loadedModel.modelKey}`,
        aliases: `unload ${name} ${loadedModel.modelKey} ${loadedModel.displayName ?? ""}`,
      });
    }
    if (loadedModels.length > 1) {
      entries.push({
        key: "unload-all",
        label: "Unload All Models",
        description: `${loadedModels.length} currently loaded`,
        command: "/unload all",
        aliases: "unload all loaded models memory",
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
  }, [backend, focusFile, hasStickyPermissions, loadedModels, model, models, recentSessions]);
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
    if (!showConstructPicker) {
      setConstructIndex(0);
      setConstructScrollOffset(0);
      return;
    }
    setConstructIndex((idx) => Math.max(0, Math.min(idx, constructMatches.length - 1)));
    setConstructScrollOffset((offset) => {
      const nextIndex = Math.max(0, Math.min(constructIndex, constructMatches.length - 1));
      if (nextIndex < offset) return nextIndex;
      if (nextIndex >= offset + CONSTRUCT_MAX_VISIBLE) {
        return Math.max(0, nextIndex - CONSTRUCT_MAX_VISIBLE + 1);
      }
      return offset;
    });
  }, [constructIndex, constructMatches.length, showConstructPicker]);

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
    onDraftConstructRefsChange?.(draftConstructRefs);
  }, [draftConstructRefs, onDraftConstructRefsChange]);

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

  function clearAttachedConstructRefs() {
    setAttachedConstructRefs([]);
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

  function submittedAttachments(text: string): AttachmentMeta[] {
    if (text.trimStart().startsWith("/")) {
      return [];
    }
    return draftFiles;
  }

  function submittedConstructRefs(text: string): ConstructRef[] {
    if (text.trimStart().startsWith("/")) {
      return [];
    }
    return draftConstructRefs;
  }

  function submitAndRecord(text: string) {
    clearExitPrompt();
    onSubmit(buildSubmittedMessage(text), submittedAttachments(text), submittedConstructRefs(text));
    setHistory((h) => [text, ...h]);
    clearInput();
    clearAttachedFiles();
    clearAttachedConstructRefs();
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

  function attachDraftConstruct(candidate: ConstructCandidate) {
    if (!constructMention) return;
    clearExitPrompt();
    const before = value.slice(0, constructMention.start);
    const after = value.slice(constructMention.end).replace(/^\s+/, "");
    const nextValue = `${before}${after}`.replace(/\s{3,}/g, "  ");
    const nextCursor = before.length;
    const nextRef: ConstructRef = {
      kind: candidate.kind,
      query: candidate.id,
      token: candidate.token,
      id: candidate.id,
      label: candidate.label,
    };
    setValue(nextValue);
    setCursor(nextCursor);
    setConstructIndex(0);
    setConstructScrollOffset(0);
    setAttachedConstructRefs((current) => {
      const key = `${nextRef.kind}:${nextRef.id ?? nextRef.query}`;
      return current.some((item) => `${item.kind}:${item.id ?? item.query}` === key)
        ? current
        : [...current, nextRef];
    });
  }

  function popAttachedFile(): boolean {
    if (attachedFiles.length === 0) return false;
    clearExitPrompt();
    setAttachedFiles((current) => current.slice(0, -1));
    return true;
  }

  function popAttachedConstructRef(): boolean {
    if (attachedConstructRefs.length === 0) return false;
    clearExitPrompt();
    setAttachedConstructRefs((current) => current.slice(0, -1));
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
    if (attachedConstructRefs.length > 0) {
      clearAttachedConstructRefs();
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

  function scrollTranscriptBy(delta: number) {
    scrollTargetBy(transcriptScrollRef?.current, delta);
  }

  function pageTranscript(direction: -1 | 1) {
    const ref = transcriptScrollRef?.current;
    if (!ref) return;
    const height = Math.max(1, ref.getViewportHeight() || 1);
    scrollTargetBy(ref, direction * height);
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

      if (!selector && !showFilePicker && !showConstructPicker) {
        if (
          transcriptScrollRef?.current
          && (
            (key.ctrl && (key.upArrow || key.downArrow))
            || (key.meta && (key.upArrow || key.downArrow))
          )
        ) {
          scrollTranscriptBy(key.upArrow ? -3 : 3);
          return;
        }
        if (key.ctrl && (key.pageUp || key.pageDown) && sidePanelScrollRef?.current) {
          const r = sidePanelScrollRef.current;
          const h = r.getViewportHeight() || 1;
          scrollTargetBy(r, key.pageUp ? -h : h);
          return;
        }
        if (key.pageUp || key.pageDown) {
          pageTranscript(key.pageUp ? -1 : 1);
          return;
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
          if (selected?.key === "model-manager") {
            onOpenModelManager?.();
          } else if (selected) {
            submitAndRecord(selected.command);
          }
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
        if (selector === "model" && input.toLowerCase() === "u") {
          const sel = models[selectorIndex];
          if (sel?.loaded) {
            submitAndRecord(`/unload ${sel.name}`);
            setSelector(null);
          }
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

      if (showConstructPicker) {
        if (key.upArrow) {
          setConstructIndex((i) => {
            const next = Math.max(0, i - 1);
            setConstructScrollOffset((off) => Math.min(off, next));
            return next;
          });
          return;
        }
        if (key.downArrow) {
          setConstructIndex((i) => {
            const next = constructMatches.length > 0 ? Math.min(constructMatches.length - 1, i + 1) : 0;
            setConstructScrollOffset((off) => Math.max(off, next - CONSTRUCT_MAX_VISIBLE + 1));
            return next;
          });
          return;
        }
        if ((key.tab || isEnter) && constructMatches[constructIndex]) {
          attachDraftConstruct(constructMatches[constructIndex]!);
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
        if (!trimmed && attachedFiles.length === 0 && attachedConstructRefs.length === 0) return;
        // Intercept bare /model and /mode
        if (trimmed.toLowerCase() === "/model") { openModelPicker(); return; }
        if (trimmed.toLowerCase() === "/mode") { openModePicker(); return; }
        if (trimmed.toLowerCase() === "/loaded" || trimmed.toLowerCase() === "/model-manager") {
          onOpenModelManager?.();
          return;
        }
        submitAndRecord(value);
        return;
      }

      // ── Backspace ──
      if (key.backspace || key.delete) {
        if (cursor === 0 && !value && popAttachedFile()) {
          return;
        }
        if (cursor === 0 && !value && popAttachedConstructRef()) {
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
  const constructStart = constructScrollOffset;
  const constructEnd = Math.min(constructMatches.length, constructStart + CONSTRUCT_MAX_VISIBLE);
  const visibleConstructs = constructMatches.slice(constructStart, constructEnd);
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
            <Text dimColor>↑↓ navigate {symbols.dot} Enter resume</Text>
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
            const runtime = describeLoadedModelRuntime(m);
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
                {runtime ? <Text color={colors.success}> {runtime}</Text> : null}
                {m.loaded ? <Text color={colors.success}> {symbols.dot}</Text> : null}
                {m.toolsEnabled ? <Text color={colors.tool}> {symbols.sword}</Text> : null}
                {m.name === model ? (
                  <Text color={colors.triforce}> {symbols.triforceSmall}</Text>
                ) : null}
              </Box>
            );
          })}
          <Box marginTop={1}>
            <Text dimColor>↑↓ navigate {symbols.dot} Enter select {symbols.dot} U unload loaded model</Text>
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
            <Text dimColor>↑↓ navigate {symbols.dot} Enter select</Text>
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
            <Text dimColor>type to filter {symbols.dot} ↑↓ navigate {symbols.dot} Enter run</Text>
          </Box>
        </Box>

      /* ── Construct autocomplete ── */
      ) : showConstructPicker ? (
        <Box
          flexDirection="column"
          borderStyle="double"
          borderColor={colors.triforce}
          paddingX={2}
          marginBottom={1}
        >
          <Box gap={1} marginBottom={1}>
            <Text bold color={colors.triforce}>{symbols.triforce} {constructPickerTitle}</Text>
            <Text color={colors.text}>#{constructMention?.kind}:{constructMention?.query || ""}</Text>
            {constructSearch.totalCount > 0 ? <Text dimColor>({constructSearch.totalCount})</Text> : null}
          </Box>
          <Box marginBottom={1}>
            <Text dimColor>project: </Text>
            <Text dimColor>{shortenPath(workspace)}</Text>
          </Box>
          {constructStatus ? (
            <Box marginBottom={1}>
              <Text color={constructStatusColor}>{constructStatus}</Text>
            </Box>
          ) : null}
          {constructLoadError ? (
            <Text color={colors.warning}>  construct index unavailable: {constructLoadError}</Text>
          ) : null}
          {constructStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {constructStart} more above</Text>
          ) : null}
          {visibleConstructs.length === 0 && !constructLoadError ? (
            <Box paddingY={1}>
              <Text dimColor>  no constructs match that query</Text>
            </Box>
          ) : null}
          {visibleConstructs.map((candidate, vi) => {
            const i = vi + constructStart;
            const isSelected = i === constructIndex;
            const isAttached = attachedConstructRefs.some((ref) => (
              ref.kind === candidate.kind && (ref.id ?? ref.query) === candidate.id
            ));
            const candidateMeta = [candidate.source, candidate.detail].filter(Boolean).join(" · ");
            return (
              <Box key={candidate.token} flexDirection="column">
                <Box gap={1}>
                  <Text color={isSelected ? colors.triforce : colors.dim}>
                    {isSelected ? symbols.arrowRight : " "}
                  </Text>
                  <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                    {candidate.token}
                  </Text>
                  <Text dimColor>{candidate.label}</Text>
                  {isAttached ? <Text color={colors.success}>attached</Text> : null}
                </Box>
                {candidateMeta ? (
                  <Box paddingLeft={2}>
                    <Text color={isSelected ? colors.accent : colors.muted}>{candidateMeta}</Text>
                  </Box>
                ) : null}
              </Box>
            );
          })}
          {constructEnd < constructMatches.length ? (
            <Text dimColor>  {symbols.triforceSmall} {constructMatches.length - constructEnd} more below</Text>
          ) : null}
          <Box marginTop={1}>
            <Text dimColor>
              type to refine {symbols.dot} ↑↓ navigate {symbols.dot} Tab/Enter attach
              {constructSearch.ambiguous ? ` ${symbols.dot} ambiguous matches stay visible until you choose` : ""}
            </Text>
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

      {(draftFiles.length > 0 || draftConstructRefs.length > 0) && !selector ? (
        <Box paddingLeft={2} flexDirection="column">
          {draftFiles.length > 0 ? (
            <Box gap={1} flexWrap="wrap">
              <Text dimColor>files</Text>
              {draftFiles.slice(0, 8).map((file) => (
                <Text key={file.path} color={colors.nayru}>
                  @{file.path}{file.lines > 0 ? ` ${file.lines}L` : ""}{file.chars > 0 ? ` ${file.chars}C` : ""}
                </Text>
              ))}
            </Box>
          ) : null}
          {draftConstructRefs.length > 0 ? (
            <Box gap={1} flexWrap="wrap">
              <Text dimColor>refs</Text>
              {draftConstructRefs.slice(0, 8).map((ref) => (
                <Text key={constructToken(ref)} color={colors.accent}>
                  {constructToken(ref)}{ref.label ? ` ${ref.label}` : ""}
                </Text>
              ))}
            </Box>
          ) : null}
          {attachedFiles.length > 0 || attachedConstructRefs.length > 0 ? (
            <Text dimColor>Backspace on an empty prompt removes the last @file or #ref</Text>
          ) : null}
        </Box>
      ) : null}

      {/* ── Input line ── */}
      <Box
        width="100%"
        borderStyle="round"
        borderColor={colors.dim}
        borderDimColor
        borderLeftColor={
          value.startsWith("!")
            ? colors.veran
            : uiModeColor(settings.uiMode, colors)
        }
        borderLeftDimColor={false}
        paddingX={1}
      >
        <Box marginRight={1}>
          {value.startsWith("!") ? (
            <Text color={colors.veran}>
              <Text bold>{symbols.compass}</Text>
              <Text dimColor> shell</Text>
            </Text>
          ) : (
            <Text color={modelColor(model, colors)}>
              <Text bold>{modelSymbol(model)}</Text>
              <Text>{` ${model}`}</Text>
            </Text>
          )}
        </Box>
        <Text color={colors.muted}>{`${symbols.arrowRight} `}</Text>
        {selector ? (
          <Text dimColor>selecting {selector}...</Text>
        ) : hint ? (
          <Text dimColor>{hint}</Text>
        ) : isStreaming ? (
          <Text dimColor>streaming...</Text>
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
