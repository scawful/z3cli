/**
 * Hook enabling xterm SGR mouse reporting and dispatching wheel events to a
 * ScrollViewRef. Designed to coexist with Ink's `useInput`: this hook parses
 * wheel events from the original TTY, while the app entrypoint strips the raw
 * mouse bytes from the proxied stdin stream before Ink sees them.
 */

import React, { useEffect } from "react";
import type { ScrollViewRef } from "ink-scroll-view";
import {
  MOUSE_DISABLE,
  MOUSE_ENABLE,
  chunkLooksLikeMouseEvent,
  parseMouseWheelEventsWithCarry,
} from "../utils/mouseEvents.js";
import { scrollTargetBy } from "../utils/scrolling.js";

export interface UseMouseScrollOptions {
  /** Lines to scroll per wheel tick. Matches most terminal scrollback steps. */
  linesPerTick?: number;
  /** Pause dispatch while a modal is open so the mouse falls back to default. */
  isActive?: boolean;
  /**
   * Route Ctrl-wheel events to this scroll view (for sidebar/content rail).
   * Transcript still receives non-modifier wheel events.
   */
  sidePanelScrollRef?: React.RefObject<ScrollViewRef | null>;
}

export function useMouseScroll(
  scrollRef: React.RefObject<ScrollViewRef | null>,
  options: UseMouseScrollOptions = {},
): void {
  const { linesPerTick = 3, isActive = true, sidePanelScrollRef } = options;
  const carryRef = React.useRef("");

  useEffect(() => {
    if (!isActive) return;
    if (!process.stdin.isTTY) return;
    if (typeof process.stdout.write !== "function") return;

    process.stdout.write(MOUSE_ENABLE);

    const onData = (chunk: Buffer | string): void => {
      const raw = typeof chunk === "string" ? chunk : chunk.toString("utf8");
      if (!carryRef.current && !chunkLooksLikeMouseEvent(raw)) {
        return;
      }

       const parsed = parseMouseWheelEventsWithCarry(raw, carryRef.current);
       carryRef.current = parsed.carry;
       if (parsed.events.length > 0) {
         for (const event of parsed.events) {
           const target = (event.modifiers.ctrl && sidePanelScrollRef?.current)
             ? sidePanelScrollRef.current
             : scrollRef.current;
           if (!target) continue;
           const delta = event.kind === "wheel-up" ? -linesPerTick : linesPerTick;
           scrollTargetBy(target, delta);
         }
        }
      };

    // Safety net: if the process exits without React unmounting (process.exit,
    // uncaught exception, fatal signal passing through), make sure the terminal
    // isn't left in mouse-reporting mode.
    const onExit = (): void => {
      process.stdout.write(MOUSE_DISABLE);
    };

    process.stdin.on("data", onData);
    process.on("exit", onExit);
    return () => {
      process.stdin.off("data", onData);
      process.off("exit", onExit);
      process.stdout.write(MOUSE_DISABLE);
    };
  }, [scrollRef, sidePanelScrollRef, linesPerTick, isActive]);
}
