import type { Message } from "../ipc/protocol.js";

/** Minimum transcript viewport height (lines) when terminal is very short. */
export const TRANSCRIPT_MIN_VIEWPORT_HEIGHT = 8;

/**
 * Rows reserved for fixed chrome below the transcript scroll area: title bar,
 * prompt block, status bar, and border lines in those two elements.
 */
export const TRANSCRIPT_RESERVED_SHELL_ROWS = 7;

/** Rows consumed by a visible backend error banner. */
export const BACKEND_ERROR_BANNER_RESERVED_ROWS = 4;

/** Terminal width below which the context rail is hidden entirely. */
export const CONTEXT_PANEL_MIN_WIDTH = 120;

/** Terminal width at which the wide context rail (36 cols) is used. */
export const CONTEXT_PANEL_WIDE_WIDTH_THRESHOLD = 150;

export const CONTEXT_PANEL_COMPACT_COLUMNS = 30;
export const CONTEXT_PANEL_WIDE_COLUMNS = 36;

/** Terminal rows at which the keyboard-legend footer starts to render. */
export const KEYBOARD_LEGEND_MIN_ROWS = 22;

/** Terminal columns below which the keyboard-legend footer is hidden. */
export const KEYBOARD_LEGEND_MIN_COLS = 80;

export function computeTranscriptViewportHeight(
  terminalRows: number,
  showKeyboardLegend: boolean = true,
  showBackendErrorBanner = false,
): number {
  const reserved = TRANSCRIPT_RESERVED_SHELL_ROWS +
    (showKeyboardLegend ? 1 : 0) +
    (showBackendErrorBanner ? BACKEND_ERROR_BANNER_RESERVED_ROWS : 0);
  return Math.max(TRANSCRIPT_MIN_VIEWPORT_HEIGHT, terminalRows - reserved);
}

export interface MessageGroup {
  id: string;
  turnId: string;
  messages: Message[];
}

export function groupMessages(messages: Message[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  for (const message of messages) {
    const turnId = message.turnId || message.id;
    const last = groups[groups.length - 1];
    if (last && last.turnId === turnId) {
      last.messages.push(message);
      continue;
    }
    groups.push({ id: `${turnId}-${groups.length}`, turnId, messages: [message] });
  }
  return groups;
}

export interface TranscriptMessageVisibility {
  showReasoning: boolean;
}

export function isReasoningCollapseHotkey(
  input: string,
  key: { ctrl?: boolean },
): boolean {
  const normalized = input.toLowerCase();
  return (key.ctrl && normalized === "r") || input === "\x12";
}

function messageHasDisplayContent(message: Message): boolean {
  if (message.role === "user") {
    return Boolean(
      message.content.trim()
      || (message.attachments && message.attachments.length > 0)
      || (message.constructRefs && message.constructRefs.length > 0),
    );
  }
  if (message.role === "tool") {
    return Boolean(message.content.trim() || message.toolArguments?.trim());
  }
  return Boolean(message.content.trim());
}

export function isTranscriptMessageVisible(
  message: Message,
  visibility: TranscriptMessageVisibility,
): boolean {
  if (message.role === "tool") {
    return messageHasDisplayContent(message);
  }
  if (message.role === "assistant") {
    return messageHasDisplayContent(message)
      || (visibility.showReasoning && Boolean(message.thinking?.trim()));
  }
  return messageHasDisplayContent(message);
}

export function filterMessageGroups(
  groups: MessageGroup[],
  visibility: TranscriptMessageVisibility,
): MessageGroup[] {
  return groups.flatMap((group) => {
    const messages = group.messages.filter((message) => isTranscriptMessageVisible(message, visibility));
    if (messages.length === 0) return [];
    return [{ ...group, messages }];
  });
}

export interface ContextPanelLayout {
  visible: boolean;
  width: number;
}

export function computeContextPanelLayout(
  width: number,
  settingsOpen: boolean,
): ContextPanelLayout {
  if (settingsOpen || width < CONTEXT_PANEL_MIN_WIDTH) {
    return { visible: false, width: 0 };
  }
  return {
    visible: true,
    width: width >= CONTEXT_PANEL_WIDE_WIDTH_THRESHOLD
      ? CONTEXT_PANEL_WIDE_COLUMNS
      : CONTEXT_PANEL_COMPACT_COLUMNS,
  };
}

export function shouldShowContextPanel(width: number, settingsOpen: boolean): boolean {
  return computeContextPanelLayout(width, settingsOpen).visible;
}

export function shouldShowKeyboardLegend(rows: number): boolean {
  return rows >= KEYBOARD_LEGEND_MIN_ROWS;
}

export interface KeyHintBarVisibilityState {
  rows: number;
  width: number;
  modalOpen: boolean;
}

/**
 * Single source of truth for whether the KeyHintBar renders. Used both to
 * decide what to mount and to reserve the matching transcript row, so the
 * two never disagree.
 */
export function shouldShowKeyHintBar(state: KeyHintBarVisibilityState): boolean {
  return shouldShowKeyboardLegend(state.rows)
    && state.width >= KEYBOARD_LEGEND_MIN_COLS
    && !state.modalOpen;
}
