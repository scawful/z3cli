/**
 * Returns the current frame string from a cycling sequence.
 * Replaces repeated useState/useEffect spinner boilerplate.
 */

import { useSyncExternalStore } from "react";

interface ClockStore {
  tick: number;
  timer: ReturnType<typeof setInterval> | null;
  listeners: Set<() => void>;
}

const clockStores = new Map<number, ClockStore>();

function getStore(intervalMs: number): ClockStore {
  const existing = clockStores.get(intervalMs);
  if (existing) return existing;
  const created: ClockStore = {
    tick: 0,
    timer: null,
    listeners: new Set<() => void>(),
  };
  clockStores.set(intervalMs, created);
  return created;
}

function subscribeClock(intervalMs: number, listener: () => void): () => void {
  const store = getStore(intervalMs);
  store.listeners.add(listener);
  if (store.timer === null) {
    store.timer = setInterval(() => {
      store.tick += 1;
      for (const notify of store.listeners) notify();
    }, intervalMs);
  }
  return () => {
    const current = getStore(intervalMs);
    current.listeners.delete(listener);
    if (current.listeners.size === 0 && current.timer) {
      clearInterval(current.timer);
      current.timer = null;
      current.tick = 0;
    }
  };
}

function getClockTick(intervalMs: number): number {
  return getStore(intervalMs).tick;
}

function subscribeStatic(_listener: () => void): () => void {
  return () => {};
}

function staticSnapshot(): number {
  return 0;
}

export function useAnimatedFrame(
  frames: readonly string[],
  intervalMs = 80,
): string {
  const isStatic = frames.length <= 1;
  const tick = useSyncExternalStore(
    isStatic
      ? subscribeStatic
      : (listener) => subscribeClock(intervalMs, listener),
    isStatic
      ? staticSnapshot
      : () => getClockTick(intervalMs),
    staticSnapshot,
  );
  if (frames.length === 0) return "";
  if (frames.length === 1) return frames[0] ?? "";
  return frames[tick % frames.length] ?? frames[0] ?? "";
}
