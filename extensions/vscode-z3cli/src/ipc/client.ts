import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface, type Interface as ReadlineInterface } from "node:readline";
import * as vscode from "vscode";
import { log, logError } from "../output.js";
import type { Z3cliConfig } from "../config.js";
import { resolveWorkspace } from "../config.js";
import type {
  BackendEvent,
  JsonRpcRequest,
  JsonRpcResponse,
  ReadyParams,
} from "./protocol.js";

export interface ClientLaunchOptions {
  cfg: Z3cliConfig;
  cwd?: string;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

interface ReadyWaiter {
  resolve: (params: ReadyParams) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

interface LaunchSpec {
  executable: string;
  args: string[];
  cwd: string;
}

const READY_TIMEOUT_MS = 30_000;

export class Z3cliClient extends EventEmitter {
  private proc: ChildProcess | null = null;
  private rl: ReadlineInterface | null = null;
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();
  private ready: ReadyParams | null = null;
  private readyWaiters: ReadyWaiter[] = [];
  private restarts = 0;
  private stopping = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private lastStderr = "";

  constructor(private opts: ClientLaunchOptions) {
    super();
  }

  isRunning(): boolean {
    return this.proc !== null;
  }

  getReady(): ReadyParams | null {
    return this.ready;
  }

  /** Build the process launch used to spawn z3cli --serve. */
  private buildLaunch(): LaunchSpec {
    const { cfg } = this.opts;
    const trailing: string[] = ["--serve"];
    const workspace = this.opts.cwd ?? resolveWorkspace(cfg);
    if (workspace) trailing.push("--workspace", workspace);
    if (cfg.rom.trim()) trailing.push("--rom", cfg.rom);
    if (cfg.chat.defaultMode.trim()) trailing.push("--mode", cfg.chat.defaultMode);
    trailing.push(...cfg.extraArgs);

    if (cfg.serveCommand.length > 0) {
      const [executable, ...rest] = cfg.serveCommand;
      return {
        executable,
        args: [...rest, ...trailing],
        cwd: workspace ?? process.cwd(),
      };
    }
    const moduleName = cfg.module || "z3cli";
    const checkoutPath = findCheckoutPath(cfg, workspace);
    const cwd = checkoutPath ?? workspace ?? process.cwd();
    if (checkoutPath) log(`using z3cli checkout ${checkoutPath}`);
    return {
      executable: cfg.pythonPath,
      args: ["-m", moduleName, ...trailing],
      cwd,
    };
  }

  start(): void {
    if (this.proc) return;
    this.stopping = false;
    this.lastStderr = "";
    const { executable, args, cwd } = this.buildLaunch();
    log(`spawn: ${executable} ${args.join(" ")} (cwd ${cwd})`);
    const proc = spawn(executable, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        Z3CLI_VSCODE: "1",
      },
      cwd,
    });
    this.proc = proc;

    this.rl = createInterface({ input: proc.stdout! });
    this.rl.on("line", (line) => this.handleLine(line));

    proc.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString().trimEnd();
      if (text) {
        this.lastStderr = text;
        log(`stderr: ${text}`);
      }
    });

    proc.on("exit", (code, signal) => {
      const exitInfo = signal ? `signal ${signal}` : `code ${code ?? -1}`;
      log(`backend exited (${exitInfo})`);
      this.rejectPending(`Backend exited (${exitInfo})`);
      this.proc = null;
      this.rl?.close();
      this.rl = null;
      this.ready = null;
      this.rejectReadyWaiters(`Backend exited (${exitInfo})`);
      this.emit("exit", { code, signal });
      if (!this.stopping) {
        if (this.lastStderr.includes("No module named z3cli")) {
          log("not restarting: Python cannot import z3cli. Set z3cli.checkoutPath or z3cli.serveCommand.");
        } else {
          this.scheduleRestart();
        }
      }
    });

    proc.on("error", (err) => {
      logError("backend process error", err);
      this.rejectPending(`Backend process error: ${err.message}`);
      this.rejectReadyWaiters(`Backend process error: ${err.message}`);
    });

    this.waitForReady().catch((err) => {
      if (!String((err as Error).message ?? "").startsWith("backend ready timed out")) {
        return;
      }
      if (!this.stopping && this.proc) {
        logError("ready timeout", err);
        log("killing backend after ready-timeout to trigger restart");
        try {
          this.proc.kill();
        } catch (killErr) {
          logError("kill after ready-timeout", killErr);
        }
      }
    });
  }

  private scheduleRestart(): void {
    const configuredMax = Math.floor(this.opts.cfg.maxRestarts);
    const maxRestarts = Number.isFinite(configuredMax) ? Math.max(0, configuredMax) : 8;
    if (maxRestarts > 0 && this.restarts >= maxRestarts) {
      log(`restart limit reached (${maxRestarts}); backend remains offline`);
      return;
    }
    this.restarts++;
    const delay = Math.min(15_000, 500 * 2 ** Math.min(this.restarts, 5));
    log(`restart in ${delay}ms (attempt ${this.restarts})`);
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.stopping) this.start();
    }, delay);
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const proc = this.proc;
    if (!proc) return;
    try {
      await this.notify("shutdown");
    } catch {
      // ignore
    }
    proc.kill();
    this.rejectPending("Backend stopped");
    this.rejectReadyWaiters("Backend stopped");
  }

  /** Wait until the backend emits its first `ready` notification. */
  waitForReady(timeoutMs = READY_TIMEOUT_MS): Promise<ReadyParams> {
    if (this.ready) return Promise.resolve(this.ready);
    return new Promise((resolve, reject) => {
      let waiter: ReadyWaiter;
      const timer = setTimeout(() => {
        this.readyWaiters = this.readyWaiters.filter((w) => w !== waiter);
        reject(new Error(`backend ready timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      waiter = {
        resolve: (params: ReadyParams) => {
          clearTimeout(timer);
          resolve(params);
        },
        reject: (err: Error) => {
          clearTimeout(timer);
          reject(err);
        },
        timer,
      };
      this.readyWaiters.push(waiter);
    });
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) return;
    let parsed: JsonRpcResponse | BackendEvent;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      log(`unparseable line: ${trimmed.slice(0, 200)}`);
      return;
    }
    if ("id" in parsed && typeof parsed.id === "number") {
      this.deliverResponse(parsed);
      return;
    }
    if ("method" in parsed) {
      this.deliverEvent(parsed as BackendEvent);
    }
  }

  private deliverResponse(msg: JsonRpcResponse): void {
    const pending = this.pending.get(msg.id);
    if (!pending) return;
    this.pending.delete(msg.id);
    clearTimeout(pending.timer);
    if (msg.error) {
      pending.reject(new Error(msg.error.message));
    } else {
      pending.resolve(msg.result);
    }
  }

  private deliverEvent(evt: BackendEvent): void {
    if (evt.method === "ready") {
      this.ready = evt.params as ReadyParams;
      this.restarts = 0;
      const waiters = this.readyWaiters;
      this.readyWaiters = [];
      for (const w of waiters) w.resolve(this.ready);
    }
    this.emit("event", evt);
    this.emit(evt.method, evt.params);
  }

  private rejectPending(reason: string): void {
    for (const [, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(new Error(reason));
    }
    this.pending.clear();
  }

  private rejectReadyWaiters(reason: string): void {
    const waiters = this.readyWaiters;
    this.readyWaiters = [];
    for (const waiter of waiters) {
      clearTimeout(waiter.timer);
      waiter.reject(new Error(reason));
    }
  }

  request<T = unknown>(method: string, params?: Record<string, unknown>, timeoutMs = 480_000): Promise<T> {
    if (!this.proc?.stdin?.writable) {
      return Promise.reject(new Error("Backend not running"));
    }
    const id = this.nextId++;
    const req: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${method} timed out after ${Math.round(timeoutMs / 1000)}s`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });
      this.proc!.stdin!.write(JSON.stringify(req) + "\n");
    });
  }

  /** Send a JSON-RPC notification (no id, no response expected). */
  notify(method: string, params?: Record<string, unknown>): Promise<void> {
    if (!this.proc?.stdin?.writable) return Promise.resolve();
    const payload = JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n";
    return new Promise((resolve) => {
      this.proc!.stdin!.write(payload, () => resolve());
    });
  }

  async runCommand(cmd: string, args: string[] = []): Promise<unknown> {
    return this.request("command", { cmd, args });
  }

  async chat(message: string, params: Record<string, unknown> = {}): Promise<unknown> {
    return this.request("chat", { message, ...params });
  }

  async cancel(): Promise<void> {
    try {
      await this.notify("cancel");
    } catch (err) {
      logError("cancel", err);
    }
  }
}

export function disposable(client: Z3cliClient): vscode.Disposable {
  return new vscode.Disposable(() => {
    void client.stop();
  });
}

function findCheckoutPath(cfg: Z3cliConfig, workspace?: string): string | undefined {
  const home = homedir();
  const candidates = [
    cfg.checkoutPath,
    process.env.Z3CLI_REPO_PATH,
    workspace,
    join(home, "src/hobby/z3cli"),
    join(home, "src/lab/z3cli"),
    join(home, "src/z3cli"),
  ];
  for (const candidate of candidates) {
    const dir = String(candidate ?? "").trim();
    if (dir && looksLikeCheckout(dir)) return dir;
  }
  return undefined;
}

function looksLikeCheckout(dir: string): boolean {
  return existsSync(join(dir, "z3cli.py"))
    && existsSync(join(dir, "src/app/__main__.py"))
    && existsSync(join(dir, "pyproject.toml"));
}
