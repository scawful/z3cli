/**
 * Frontend-side CLI argument parsing.
 *
 * The frontend forwards most argv to the Python backend but intercepts a small
 * set of UX-oriented flags (currently only --resume). Keeping the parser pure
 * lets it be unit-tested without spawning anything.
 */

export interface ParsedCliArgs {
  /** Args safe to forward to the Python backend subprocess. */
  backendArgs: string[];
  /** Commands to dispatch once the backend reports config-ready. */
  startupCommands: string[];
}

/**
 * True if any queued startup command would restore a prior session, so the
 * welcome banner would be redundant (or worse, compete with the resume picker).
 */
export function shouldSuppressWelcome(commands: readonly string[]): boolean {
  return commands.some((c) => c.trim().startsWith("/resume"));
}

/**
 * Parse frontend-owned flags out of argv. Unknown flags are forwarded
 * untouched so the backend can still handle them.
 */
export function parseCliArgs(argv: readonly string[]): ParsedCliArgs {
  const backendArgs: string[] = [];
  const startupCommands: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === undefined) continue;
    if (arg === "--resume") {
      const next = argv[i + 1];
      if (typeof next === "string" && next.length > 0 && !next.startsWith("-")) {
        startupCommands.push(`/resume ${next}`);
        i += 1;
      } else {
        startupCommands.push("/resume");
      }
      continue;
    }
    if (arg.startsWith("--resume=")) {
      const value = arg.slice("--resume=".length).trim();
      startupCommands.push(value ? `/resume ${value}` : "/resume");
      continue;
    }
    backendArgs.push(arg);
  }
  return { backendArgs, startupCommands };
}
