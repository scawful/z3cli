/**
 * Text input with slash-command autocomplete, command history,
 * and interactive model/mode pickers.
 */

import React, { useEffect, useMemo, useState } from "react";
import { Box, Text, useInput } from "ink";
import { createInterface } from "node:readline";
import { colors, symbols, modelColor, modelSymbol } from "../theme/index.js";
import type { ModelInfo } from "../ipc/protocol.js";
import type { SessionInfo } from "../commands/index.js";

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
  { name: "/mode",      args: "<name>",        description: "Set routing mode" },
  { name: "/models",    args: "",              description: "List Zelda models" },
  { name: "/modes",     args: "",              description: "List routing modes" },
  { name: "/status",    args: "",              description: "Connection and state info" },
  { name: "/servers",   args: "",              description: "Tool server info" },
  { name: "/tools",     args: "<on|off>",      description: "Toggle tool use" },
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
  { name: "manual",     description: "Route to active model only" },
  { name: "oracle",     description: "Keyword-based model routing" },
  { name: "switchhook", description: "Plan vs act routing" },
  { name: "broadcast",  description: "Fan out to multiple models" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type SelectorKind = null | "model" | "mode" | "session";

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
const STEM_RE = /^\d{4}-\d{2}-\d{2}_\d{6}_?/;
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"] as const;

function sessionSlug(name: string): string {
  const slug = name.replace(STEM_RE, "");
  if (slug) return slug;
  // No slug — fall back to the time portion: "153042" → "15:30"
  const m = name.match(/_(\d{2})(\d{2})\d{2}$/);
  return m ? `${m[1]}:${m[2]}` : name.slice(0, 8);
}

function sessionDate(iso: string): string {
  if (!iso) return "?";
  try {
    const d = new Date(iso);
    const mon = MONTHS[d.getMonth()] ?? "?";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${mon} ${d.getDate()} ${hh}:${mm}`;
  } catch {
    return iso.slice(0, 10);
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PromptInputProps {
  mode: string;
  model: string;
  models: ModelInfo[];
  disabled: boolean;
  isStreaming?: boolean;
  hint?: string;
  sessions?: SessionInfo[] | null;
  onSessionClose?: () => void;
  onSubmit: (text: string) => void;
}

export function PromptInput({
  mode,
  model,
  models,
  disabled,
  isStreaming,
  hint,
  sessions,
  onSessionClose,
  onSubmit,
}: PromptInputProps): React.ReactElement {
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

  // Auto-open session picker when sessions list arrives from a command
  useEffect(() => {
    if (sessions && sessions.length > 0) {
      setSelector("session");
      setSelectorIndex(0);
      setSessionScrollOffset(0);
    }
  }, [sessions]);

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

  // ---- Helpers ----

  function clearInput() {
    setValue("");
    setCursor(0);
    setHistoryIndex(-1);
    setSelectedCompletion(0);
  }

  function openModelPicker() {
    setSelector("model");
    setSelectorIndex(Math.max(0, models.findIndex((m) => m.name === model)));
    clearInput();
  }

  function openModePicker() {
    setSelector("mode");
    setSelectorIndex(Math.max(0, MODES.findIndex((m) => m.name === mode)));
    clearInput();
  }

  function submitAndRecord(text: string) {
    onSubmit(text);
    setHistory((h) => [text, ...h]);
    clearInput();
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
      // Escape: cancel selector
      if (key.escape) {
        if (selector) {
          setSelector(null);
          clearInput();
          if (selector === "session") onSessionClose?.();
        }
        return;
      }

      // ── Session selector ──
      if (selector === "session") {
        const list = sessions ?? [];
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
            const next = Math.min(list.length - 1, i + 1);
            setSessionScrollOffset((off) => Math.max(off, next - SESSION_MAX_VISIBLE + 1));
            return next;
          });
          return;
        }
        if (key.return) {
          const sel = list[selectorIndex];
          if (sel) submitAndRecord(`/resume ${sel.name}`);
          setSelector(null);
          onSessionClose?.();
          return;
        }
        if (input === "\x03") {
          setSelector(null);
          clearInput();
          onSessionClose?.();
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
        if (key.return) {
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
        if (input === "\x03") {
          setSelector(null);
          clearInput();
          return;
        }
        return; // swallow all other keys in selector mode
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
      if (key.return) {
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
        if (!trimmed) return;
        // Intercept bare /model and /mode
        if (trimmed.toLowerCase() === "/model") { openModelPicker(); return; }
        if (trimmed.toLowerCase() === "/mode") { openModePicker(); return; }
        submitAndRecord(value);
        return;
      }

      // ── Backspace ──
      if (key.backspace || key.delete) {
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
      if (input === "\x03") {
        if (value) { clearInput(); } else { process.exit(0); }
        return;
      }
      // Ctrl+A / Ctrl+E
      if (input === "\x01") { setCursor(0); return; }
      if (input === "\x05") { setCursor(value.length); return; }

      // Ctrl+U — clear to beginning of line
      if (input === "\x15") {
        setValue((v) => v.slice(cursor));
        setCursor(0);
        return;
      }
      // Ctrl+K — kill to end of line
      if (input === "\x0B") {
        setValue((v) => v.slice(0, cursor));
        return;
      }
      // Ctrl+W — delete word before cursor
      if (input === "\x17") {
        const boundary = wordBoundaryLeft(value, cursor);
        setValue((v) => v.slice(0, boundary) + v.slice(cursor));
        setCursor(boundary);
        return;
      }
      // Ctrl+D — exit when empty, forward delete otherwise
      if (input === "\x04") {
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
  const sessionList = sessions ?? [];
  const sesStart = sessionScrollOffset;
  const sesEnd = Math.min(sessionList.length, sesStart + SESSION_MAX_VISIBLE);
  const visibleSessions = sessionList.slice(sesStart, sesEnd);

  return (
    <Box flexDirection="column">
      {/* ── Session picker ── */}
      {selector === "session" ? (
        <Box flexDirection="column" paddingLeft={2}>
          <Box gap={1}>
            <Text bold color={colors.triforce}>Resume session</Text>
            <Text dimColor>({sessionList.length})</Text>
          </Box>
          {sesStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {sesStart} more above</Text>
          ) : null}
          {visibleSessions.map((s, vi) => {
            const i = vi + sesStart;
            const isSelected = i === selectorIndex;
            const slug = sessionSlug(s.name).padEnd(22);
            const date = sessionDate(s.started);
            const mc = modelColor(s.activeModel);
            return (
              <Box key={s.name} gap={1}>
                <Text color={isSelected ? colors.triforce : colors.dim}>
                  {isSelected ? symbols.arrowRight : " "}
                </Text>
                <Text color={isSelected ? colors.text : colors.muted} bold={isSelected}>
                  {slug}
                </Text>
                <Text dimColor>{date.padEnd(14)}</Text>
                <Text color={isSelected ? mc : colors.muted} bold={isSelected}>
                  {s.activeModel.padEnd(10)}
                </Text>
                <Text dimColor>{s.messages}m</Text>
              </Box>
            );
          })}
          {sesEnd < sessionList.length ? (
            <Text dimColor>  {symbols.triforceSmall} {sessionList.length - sesEnd} more below</Text>
          ) : null}
          <Text dimColor>{"  "}↑↓ navigate {symbols.dot} Enter resume {symbols.dot} Esc cancel</Text>
        </Box>

      /* ── Model picker ── */
      ) : selector === "model" ? (
        <Box flexDirection="column" paddingLeft={2}>
          <Box gap={1} marginBottom={0}>
            <Text bold color={colors.triforce}>Select model</Text>
          </Box>
          {models.map((m, i) => (
            <Box key={m.name} gap={1}>
              <Text color={i === selectorIndex ? colors.triforce : colors.dim}>
                {i === selectorIndex ? symbols.arrowRight : " "}
              </Text>
              <Text color={modelColor(m.name)}>{modelSymbol(m.name)}</Text>
              <Text
                color={i === selectorIndex ? modelColor(m.name) : colors.muted}
                bold={i === selectorIndex}
              >
                {m.name.padEnd(18)}
              </Text>
              <Text dimColor>{m.role}</Text>
              {m.loaded ? <Text color={colors.success}> {symbols.dot}</Text> : null}
              {m.toolsEnabled ? <Text color={colors.tool}> {symbols.sword}</Text> : null}
              {m.name === model ? (
                <Text color={colors.triforce}> {symbols.triforceSmall}</Text>
              ) : null}
            </Box>
          ))}
          <Text dimColor>  {symbols.dot} {symbols.arrowRight} navigate {symbols.dot} Enter select {symbols.dot} Esc cancel</Text>
        </Box>

      /* ── Mode picker ── */
      ) : selector === "mode" ? (
        <Box flexDirection="column" paddingLeft={2}>
          <Box gap={1} marginBottom={0}>
            <Text bold color={colors.triforce}>Select routing mode</Text>
          </Box>
          {MODES.map((m, i) => (
            <Box key={m.name} gap={1}>
              <Text color={i === selectorIndex ? colors.triforce : colors.dim}>
                {i === selectorIndex ? symbols.arrowRight : " "}
              </Text>
              <Text
                color={i === selectorIndex ? colors.accent : colors.muted}
                bold={i === selectorIndex}
              >
                {m.name.padEnd(14)}
              </Text>
              <Text dimColor>{m.description}</Text>
              {m.name === mode ? (
                <Text color={colors.triforce}> {symbols.triforceSmall}</Text>
              ) : null}
            </Box>
          ))}
          <Text dimColor>  {symbols.dot} {symbols.arrowRight} navigate {symbols.dot} Enter select {symbols.dot} Esc cancel</Text>
        </Box>

      /* ── Command autocomplete ── */
      ) : showCompletions ? (
        <Box flexDirection="column" paddingLeft={2}>
          {compStart > 0 ? (
            <Text dimColor>  {symbols.triforceSmall} {compStart} more above</Text>
          ) : null}
          {visibleCompletions.map((cmd, vi) => {
            const i = vi + compStart;
            return (
              <Box key={cmd.name} gap={1}>
                <Text
                  color={i === selectedCompletion ? colors.triforce : colors.dim}
                  bold={i === selectedCompletion}
                >
                  {i === selectedCompletion ? symbols.arrowRight : " "}
                </Text>
                <Text
                  color={i === selectedCompletion ? colors.text : colors.muted}
                  bold={i === selectedCompletion}
                >
                  {cmd.name.padEnd(14)}
                </Text>
                {cmd.args ? <Text dimColor>{cmd.args.padEnd(14)}</Text> : <Text>{"".padEnd(14)}</Text>}
                <Text dimColor>{cmd.description}</Text>
              </Box>
            );
          })}
          {compEnd < completions.length ? (
            <Text dimColor>  {symbols.triforceSmall} {completions.length - compEnd} more below</Text>
          ) : null}
        </Box>
      ) : null}

      {/* ── Input line ── */}
      <Box borderStyle="round" borderColor={modelColor(model)} paddingX={1}>
        <Text color={modelColor(model)} bold>
          {modelSymbol(model)}
        </Text>
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
    </Box>
  );
}
