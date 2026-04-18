/**
 * Pure helpers for deciding whether the backend looks unhealthy right now.
 *
 * The frontend can't ping the backend directly — we infer health from the
 * request counters published on every config update.
 */

export interface BackendHealthInput {
  requestErrorCount?: number;
  requestSuccessCount?: number;
  lastRequestStatus?: string;
  /**
   * If the user has dismissed the banner, this is the errorCount at the time.
   * A later error (errorCount > dismissedErrorCount) re-opens the banner.
   */
  dismissedErrorCount?: number | null;
}

/**
 * Show a persistent banner when requests are failing from the start or the
 * most recent request errored. Session analysis showed 6/10 recent sessions
 * silently died after the first model request — this banner stops the
 * "switch models in a panic" spiral by surfacing the failure explicitly.
 */
export function shouldShowBackendErrorBanner(config: BackendHealthInput | null | undefined): boolean {
  if (!config) return false;
  const errors = config.requestErrorCount ?? 0;
  if (errors <= 0) return false;
  const dismissedAt = config.dismissedErrorCount ?? null;
  if (dismissedAt !== null && errors <= dismissedAt) return false;
  const success = config.requestSuccessCount ?? 0;
  const lastStatus = (config.lastRequestStatus ?? "").toLowerCase();
  return lastStatus === "error" || success === 0;
}

export function backendErrorHint(config: BackendHealthInput | null | undefined): string {
  if (!config) return "";
  const errors = config.requestErrorCount ?? 0;
  const success = config.requestSuccessCount ?? 0;
  if (errors > 0 && success === 0) {
    return "no request has succeeded yet — check LM Studio / try /backend";
  }
  return "last request failed — retry, switch model, or /backend";
}
