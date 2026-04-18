/**
 * Pure parser for xterm SGR mouse escape sequences.
 *
 * Emitter escape codes (side effects) live in the useMouseScroll hook.
 * This file is stateless so the parser can be unit-tested without a TTY.
 *
 * SGR format (enabled by CSI ?1006h):
 *   ESC [ < btn ; col ; row M   (press / wheel)
 *   ESC [ < btn ; col ; row m   (release)
 *
 * Wheel events always arrive with a trailing "M" since there is no release.
 * Button code 64 = wheel-up, 65 = wheel-down (mod bits 4-7 add Shift/Alt/Ctrl
 * flags which we ignore — we care about the low 6 bits).
 */

export interface MouseWheelEvent {
  kind: "wheel-up" | "wheel-down";
  col: number;
  row: number;
  modifiers: {
    shift: boolean;
    alt: boolean;
    ctrl: boolean;
  };
}

export interface ParsedMouseWheelChunk {
  events: MouseWheelEvent[];
  /**
   * Non-mouse bytes from this chunk that should continue through normal input
   * handling after SGR mouse reporting sequences are removed.
   */
  passthrough: string;
  /**
   * Unmatched trailing bytes that look like the start of a future mouse event.
   */
  carry: string;
}

const SGR_PATTERN = /\x1b\[<(\d+);(\d+);(\d+)([Mm])/g;
const MOUSE_PREFIX = "\x1b[<";
const COMPLETE_WHEEL_EVENT = /^\x1b\[<(\d+);(\d+);(\d+)[Mm]$/;
const MOUSE_CHUNK_PREFIX = /^\x1b\[<(?:\d+(?:;\d*)*)?$/;

/**
 * Extract wheel events from a raw stdin chunk. Non-wheel events (click, move,
 * drag) are ignored — they fall through to Ink's input handling.
 */
export function parseMouseWheelEvents(raw: string): MouseWheelEvent[] {
  return parseMouseWheelEventsWithCarry(raw).events;
}

/**
 * Parse mouse-wheel events from an input chunk that may be split across
 * multiple `stdin` callbacks.
 */
export function parseMouseWheelEventsWithCarry(
  raw: string,
  carry = "",
): ParsedMouseWheelChunk {
  const events: MouseWheelEvent[] = [];
  const text = `${carry}${raw}`;
  let passthrough = "";

  if (!text || !text.includes(MOUSE_PREFIX)) {
    return { events, passthrough: text, carry: "" };
  }

  SGR_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  let cursor = 0;
  while ((match = SGR_PATTERN.exec(text)) !== null) {
    if (match.index > cursor) {
      passthrough += text.slice(cursor, match.index);
    }

    const terminator = match[4];
    if (terminator === "M") {
      const rawButton = Number(match[1]);
      const col = Number(match[2]);
      const row = Number(match[3]);
      const button = rawButton & 0b11111111;
      if ((button & 64) !== 0) {
        const direction = button & 1;
        events.push({
          kind: direction === 0 ? "wheel-up" : "wheel-down",
          col,
          row,
          modifiers: {
            shift: (button & 4) !== 0,
            alt: (button & 8) !== 0,
            ctrl: (button & 16) !== 0,
          },
        });
      }
    }

    cursor = SGR_PATTERN.lastIndex;
  }

  let nextCarry = "";
  const tail = text.slice(cursor);
  if (tail) {
    const restart = tail.lastIndexOf(MOUSE_PREFIX);
    if (restart >= 0) {
      const candidate = tail.slice(restart);
      if (!COMPLETE_WHEEL_EVENT.test(candidate) && /^\x1b\[<[\d;]*$/.test(candidate)) {
        passthrough += tail.slice(0, restart);
        nextCarry = candidate;
      } else {
        passthrough += tail;
      }
    } else {
      passthrough += tail;
    }
  }

  return { events, passthrough, carry: nextCarry };
}

/**
 * Detect whether a raw stdin chunk contains any SGR mouse-event bytes. Used
 * by the hook to early-return on non-mouse input without allocating a regex
 * match.
 */
export function chunkLooksLikeMouseEvent(raw: string): boolean {
  if (!raw) return false;
  if (!raw.includes(MOUSE_PREFIX)) return false;

  let remaining = raw;
  while (remaining.length > 0) {
    const start = remaining.indexOf(MOUSE_PREFIX);
    if (start < 0) return false;

    const candidate = remaining.slice(start);
    if (/^\x1b\[<\d+;\d+;\d+[Mm]/.test(candidate)) return true;
    if (MOUSE_CHUNK_PREFIX.test(candidate)) return true;

    remaining = remaining.slice(start + MOUSE_PREFIX.length);
  }
  return true;
}

/**
 * Escape sequences for toggling xterm SGR mouse tracking. Exposed so the hook
 * keeps side effects in one place.
 */
export const MOUSE_ENABLE = "\x1b[?1000h\x1b[?1006h";
export const MOUSE_DISABLE = "\x1b[?1006l\x1b[?1000l";
