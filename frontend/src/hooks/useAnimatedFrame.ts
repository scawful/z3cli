/**
 * Returns the current frame string from a cycling sequence.
 * Replaces repeated useState/useEffect spinner boilerplate.
 */

import { useState, useEffect } from "react";

export function useAnimatedFrame(
  frames: readonly string[],
  intervalMs = 80,
): string {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setIndex((i) => i + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return frames[index % frames.length]!;
}
