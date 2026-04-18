import { PassThrough } from "node:stream";
import { parseMouseWheelEventsWithCarry } from "./mouseEvents.js";

type TtyReadable = PassThrough & NodeJS.ReadStream & {
  setRawMode?: (mode: boolean) => TtyReadable;
  ref?: () => TtyReadable;
  unref?: () => TtyReadable;
  isRaw?: boolean;
  fd?: number;
};

/**
 * Proxy stdin for Ink so SGR mouse reporting bytes never reach `useInput`.
 * The wheel hook still listens to the original TTY and parses those bytes
 * there; this stream exists only to forward non-mouse input to Ink.
 */
export function createMouseFilteredStdin(
  source: NodeJS.ReadStream = process.stdin,
): NodeJS.ReadStream {
  const filtered = new PassThrough() as TtyReadable;
  let carry = "";

  const onData = (chunk: Buffer | string): void => {
    const raw = typeof chunk === "string" ? chunk : chunk.toString("utf8");
    const parsed = parseMouseWheelEventsWithCarry(raw, carry);
    carry = parsed.carry;
    if (parsed.passthrough.length > 0) {
      filtered.write(parsed.passthrough);
    }
  };

  const onEnd = (): void => {
    filtered.end();
  };

  const onError = (error: Error): void => {
    filtered.emit("error", error);
  };

  const cleanup = (): void => {
    source.off("data", onData);
    source.off("end", onEnd);
    source.off("error", onError);
  };

  source.on("data", onData);
  source.on("end", onEnd);
  source.on("error", onError);

  const destroy = filtered.destroy.bind(filtered);
  filtered.destroy = ((error?: Error) => {
    cleanup();
    return destroy(error);
  }) as typeof filtered.destroy;

  Object.defineProperty(filtered, "isTTY", {
    configurable: true,
    enumerable: true,
    get: () => Boolean(source.isTTY),
  });

  Object.defineProperty(filtered, "isRaw", {
    configurable: true,
    enumerable: true,
    get: () => Boolean((source as NodeJS.ReadStream & { isRaw?: boolean }).isRaw),
  });

  if (typeof (source as TtyReadable).fd === "number") {
    Object.defineProperty(filtered, "fd", {
      configurable: true,
      enumerable: true,
      get: () => (source as TtyReadable).fd,
    });
  }

  filtered.setRawMode = (mode: boolean): TtyReadable => {
    source.setRawMode?.(mode);
    return filtered;
  };

  filtered.ref = (): TtyReadable => {
    source.ref?.();
    return filtered;
  };

  filtered.unref = (): TtyReadable => {
    source.unref?.();
    return filtered;
  };

  return filtered;
}
