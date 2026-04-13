/**
 * Path display utilities — shorten absolute paths for terminal display.
 */

/** ~/src/hobby/z3cli → ~/z3cli */
export function shortenPath(p: string): string {
  return p
    .replace(/^\/Users\/[^/]+/, "~")
    .replace(/\/src\/hobby\//, "/");
}

/** Last path segment, empty string if none. */
export function basename(p: string): string {
  return p.split("/").pop() ?? "";
}
