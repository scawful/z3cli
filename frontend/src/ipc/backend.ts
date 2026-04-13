/**
 * Spawns the Python z3cli backend and communicates via JSON Lines over stdio.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { EventEmitter } from "node:events";
import type {
  JsonRpcRequest,
  JsonRpcResponse,
  BackendEvent,
} from "./protocol.js";

export class Backend extends EventEmitter {
  private proc: ChildProcess | null = null;
  private nextId = 1;
  private pending = new Map<
    number,
    { resolve: (v: unknown) => void; reject: (e: Error) => void }
  >();

  constructor(
    private pythonPath: string,
    private backendArgs: string[] = [],
  ) {
    super();
  }

  /** Spawn the Python backend in --serve mode. */
  start(): void {
    this.proc = spawn(this.pythonPath, ["-m", "z3cli", "--serve", ...this.backendArgs], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
    });

    // Parse newline-delimited JSON from stdout
    const rl = createInterface({ input: this.proc.stdout! });
    rl.on("line", (line) => {
      if (!line.trim()) return;
      try {
        const msg = JSON.parse(line);
        this.handleMessage(msg);
      } catch {
        // Ignore unparseable lines (e.g. Python print() debug output)
      }
    });

    // Forward stderr for debugging
    this.proc.stderr?.on("data", (chunk: Buffer) => {
      this.emit("stderr", chunk.toString());
    });

    this.proc.on("exit", (code) => {
      this.emit("exit", code);
      this.proc = null;
    });
  }

  private handleMessage(msg: JsonRpcResponse | BackendEvent): void {
    // Response to a request
    if ("id" in msg && typeof msg.id === "number") {
      const p = this.pending.get(msg.id);
      if (p) {
        this.pending.delete(msg.id);
        if ("error" in msg && msg.error) {
          p.reject(new Error(msg.error.message));
        } else {
          p.resolve(msg.result);
        }
      }
      return;
    }

    // Streaming notification
    if ("method" in msg) {
      this.emit("event", msg as BackendEvent);
      this.emit(msg.method, (msg as BackendEvent).params);
    }
  }

  /** Send a JSON-RPC request and wait for the response. */
  async request(method: string, params?: Record<string, unknown>): Promise<unknown> {
    if (!this.proc?.stdin?.writable) {
      throw new Error("Backend not running");
    }
    const id = this.nextId++;
    const req: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc!.stdin!.write(JSON.stringify(req) + "\n");
    });
  }

  /** Send a fire-and-forget notification (no response expected). */
  notify(method: string, params?: Record<string, unknown>): void {
    if (!this.proc?.stdin?.writable) return;
    const msg = { jsonrpc: "2.0", method, params };
    this.proc.stdin.write(JSON.stringify(msg) + "\n");
  }

  /** Send a chat message. Streaming events arrive via the 'event' emitter. */
  async chat(message: string, model?: string): Promise<void> {
    this.notify("chat", { message, model });
  }

  /** Execute a slash command. */
  async command(cmd: string, args: string[] = []): Promise<unknown> {
    return this.request("command", { cmd, args });
  }

  /** Cancel the active streaming response. */
  cancel(): void {
    this.notify("cancel");
  }

  /** Gracefully shut down the backend. */
  stop(): void {
    if (this.proc) {
      this.notify("shutdown");
      // Give it a moment to clean up, then force kill
      setTimeout(() => {
        if (this.proc) {
          this.proc.kill("SIGTERM");
        }
      }, 2000);
    }
  }

  get running(): boolean {
    return this.proc !== null && this.proc.exitCode === null;
  }
}
