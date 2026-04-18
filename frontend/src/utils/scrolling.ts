export interface ScrollClampTarget {
  getScrollOffset: () => number;
  getBottomOffset: () => number;
  scrollTo: (offset: number) => void;
}

export function clampScrollOffset(offset: number, bottom: number): number {
  return Math.max(0, Math.min(offset, bottom));
}

export function scrollTargetBy(target: ScrollClampTarget | null | undefined, delta: number): void {
  if (!target) return;

  const nextOffset = target.getScrollOffset() + delta;
  const clamped = clampScrollOffset(nextOffset, target.getBottomOffset());
  if (clamped === target.getScrollOffset()) return;

  target.scrollTo(clamped);
}
