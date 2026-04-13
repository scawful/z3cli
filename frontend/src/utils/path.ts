/**
 * Path display utilities — shorten absolute paths for terminal display.
 */

export function shortenPath(p: string): string {
  return p.replace(/^\/Users\/[^/]+/, "~");
}

/** Last path segment, empty string if none. */
export function basename(p: string): string {
  return p.split("/").pop() ?? "";
}
