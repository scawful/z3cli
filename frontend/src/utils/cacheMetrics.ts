/**
 * Anthropic prompt-cache metrics: hit rate, compact display, estimated savings.
 * Pure helpers — no React, no side effects.
 */

/** Compact k/M formatter that mirrors theme.formatTokens's numeric output. */
function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return `${n}`;
}

/**
 * Fraction of input tokens served from cache, in [0, 1].
 * Returns 0 when no cache activity has happened so callers never see NaN.
 */
export function cacheHitRate(cacheReadTokens: number, cacheCreationTokens: number): number {
  const total = cacheReadTokens + cacheCreationTokens;
  if (total <= 0) return 0;
  return cacheReadTokens / total;
}

/**
 * Short one-line display suitable for the StatusBar.
 * Before any reads: "caching on · <N> cached" to signal that caching is warming.
 * Once reads have happened: "<P>% hit · <N> cached".
 */
export function formatCacheCompact(read: number, creation: number): string {
  const total = read + creation;
  if (total <= 0) return "";
  if (read <= 0) {
    return `caching on · ${compactNumber(creation)} cached`;
  }
  const pct = Math.round(cacheHitRate(read, creation) * 100);
  return `${pct}% hit · ${compactNumber(total)} cached`;
}

/**
 * Estimated savings in cents vs. paying full input price for those same tokens.
 *
 * Anthropic pricing: cache reads = 10% of input, cache writes = 125% of input.
 * So each cached read saves 90% of the input price, and each cache write costs
 * an extra 25% up front. The third argument (`normalInputTokens`) is accepted
 * for API symmetry but not used in the savings calc — savings only depend on
 * the cache token counts and the input price.
 *
 * Returns a value in cents (can be negative if writes dominate reads).
 */
export function estimatedSavingsCents(
  read: number,
  creation: number,
  _normalInputTokens: number,
  modelPricePerMInput: number = 3.0,
): number {
  const savingsDollars = ((read * 0.9) - (creation * 0.25)) * modelPricePerMInput / 1_000_000;
  return savingsDollars * 100;
}
