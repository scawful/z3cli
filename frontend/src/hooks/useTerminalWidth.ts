import { useEffect, useState } from "react";

function currentSize(): { width: number; rows: number } {
  return {
    width: process.stdout.columns ?? 0,
    rows: process.stdout.rows ?? 24,
  };
}

const RESIZE_THROTTLE_MS = 80;

export interface TerminalSize {
  width: number;
  rows: number;
}

/**
 * Live terminal dimensions (columns and rows), throttled on stdout resize.
 */
export function useTerminalSize(): TerminalSize {
  const [size, setSize] = useState(currentSize);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const handleResize = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        setSize(currentSize());
      }, RESIZE_THROTTLE_MS);
    };
    process.stdout.on("resize", handleResize);
    return () => {
      process.stdout.off("resize", handleResize);
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };
  }, []);

  return size;
}

export function useTerminalWidth(): number {
  return useTerminalSize().width;
}
