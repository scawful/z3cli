/**
 * Request-scoped stream gating helpers.
 *
 * Frontend receives a mixed event stream and should only render events
 * that belong to the currently active request id.
 */

export interface RequestScopeDecision {
  nextActiveRequestId: string;
  accept: boolean;
}

export function evaluateRequestScope(
  activeRequestId: string,
  requestIdValue: unknown,
): RequestScopeDecision {
  const incomingRequestId =
    typeof requestIdValue === "string" ? requestIdValue.trim() : "";
  const nextActiveRequestId =
    !activeRequestId && incomingRequestId ? incomingRequestId : activeRequestId;
  const accept =
    !nextActiveRequestId
    || !incomingRequestId
    || nextActiveRequestId === incomingRequestId;
  return { nextActiveRequestId, accept };
}

export function cancelRequestTarget(activeRequestId: string): string | undefined {
  return activeRequestId || undefined;
}

