import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { PassThrough } from "node:stream";
import { createMouseFilteredStdin } from "./mouseStdin.js";

type MockReadStream = PassThrough & NodeJS.ReadStream & {
  setRawMode: (mode: boolean) => MockReadStream;
  ref: () => MockReadStream;
  unref: () => MockReadStream;
  isRaw?: boolean;
  refCount: number;
};

function createMockReadStream(): MockReadStream {
  const source = new PassThrough() as MockReadStream;
  Object.defineProperty(source, "isTTY", {
    configurable: true,
    enumerable: true,
    value: true,
  });
  source.refCount = 0;
  source.setRawMode = (mode: boolean): MockReadStream => {
    source.isRaw = mode;
    return source;
  };
  source.ref = (): MockReadStream => {
    source.refCount += 1;
    return source;
  };
  source.unref = (): MockReadStream => {
    source.refCount -= 1;
    return source;
  };
  return source;
}

test("createMouseFilteredStdin strips mouse reporting bytes before Ink sees them", async () => {
  const source = createMockReadStream();
  const filtered = createMouseFilteredStdin(source);
  const chunks: string[] = [];

  filtered.on("data", (chunk: Buffer | string) => {
    chunks.push(typeof chunk === "string" ? chunk : chunk.toString("utf8"));
  });

  source.write("ab");
  source.write("\x1b[<64;10;5M");
  source.write("cd");
  source.end();
  await once(filtered, "end");

  assert.equal(chunks.join(""), "abcd");
  filtered.destroy();
});

test("createMouseFilteredStdin preserves split mouse carry across chunks", async () => {
  const source = createMockReadStream();
  const filtered = createMouseFilteredStdin(source);
  const chunks: string[] = [];

  filtered.on("data", (chunk: Buffer | string) => {
    chunks.push(typeof chunk === "string" ? chunk : chunk.toString("utf8"));
  });

  source.write("ab\x1b[<64;10");
  source.write(";5Mcd");
  source.end();
  await once(filtered, "end");

  assert.equal(chunks.join(""), "abcd");
  filtered.destroy();
});

test("createMouseFilteredStdin forwards raw-mode toggles to the source tty", () => {
  const source = createMockReadStream();
  const filtered = createMouseFilteredStdin(source) as NodeJS.ReadStream & {
    setRawMode?: (mode: boolean) => void;
  };

  filtered.setRawMode?.(true);
  assert.equal(source.isRaw, true);

  filtered.setRawMode?.(false);
  assert.equal(source.isRaw, false);
  filtered.destroy();
});

test("createMouseFilteredStdin forwards ref and unref to the source tty", () => {
  const source = createMockReadStream();
  const filtered = createMouseFilteredStdin(source) as NodeJS.ReadStream & {
    ref?: () => void;
    unref?: () => void;
  };

  filtered.ref?.();
  assert.equal(source.refCount, 1);

  filtered.unref?.();
  assert.equal(source.refCount, 0);
  filtered.destroy();
});
