import type { Message } from "../ipc/protocol.js";

/** Minimum transcript viewport height (lines) when terminal is very short. */
export const TRANSCRIPT_MIN_VIEWPORT_HEIGHT = 8;

/**
 * Rows reserved for chrome below the transcript scroll area: title bar, prompt
 * block, status bar, keyboard legend, and flex gaps.
 */
export const TRANSCRIPT_RESERVED_SHELL_ROWS = 15;

export function computeTranscriptViewportHeight(terminalRows: number): number {
  return Math.max(TRANSCRIPT_MIN_VIEWPORT_HEIGHT, terminalRows - TRANSCRIPT_RESERVED_SHELL_ROWS);
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

export function shouldShowContextPanel(width: number, settingsOpen: boolean): boolean {
  return width >= 140 && !settingsOpen;
}
