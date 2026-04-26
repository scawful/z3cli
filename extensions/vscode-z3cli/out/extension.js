"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/extension.ts
var extension_exports = {};
__export(extension_exports, {
  activate: () => activate,
  deactivate: () => deactivate
});
module.exports = __toCommonJS(extension_exports);
var vscode9 = __toESM(require("vscode"));

// src/output.ts
var vscode = __toESM(require("vscode"));
var channel = null;
function output() {
  if (!channel) {
    channel = vscode.window.createOutputChannel("Z3CLI");
  }
  return channel;
}
function log(message) {
  output().appendLine(`[${(/* @__PURE__ */ new Date()).toISOString()}] ${message}`);
}
function logError(message, err) {
  const detail = err instanceof Error ? `${err.message}
${err.stack ?? ""}` : String(err);
  log(`${message}: ${detail}`);
}

// src/config.ts
var vscode2 = __toESM(require("vscode"));
function readConfig() {
  const cfg = vscode2.workspace.getConfiguration("z3cli");
  const fim = cfg.get("fim") ?? {};
  const chat = cfg.get("chat") ?? {};
  return {
    pythonPath: cfg.get("pythonPath", "python3"),
    module: cfg.get("module", "z3cli"),
    checkoutPath: cfg.get("checkoutPath", ""),
    serveCommand: cfg.get("serveCommand", []),
    extraArgs: cfg.get("extraArgs", []),
    maxRestarts: cfg.get("maxRestarts", 8),
    workspace: cfg.get("workspace", ""),
    rom: cfg.get("rom", ""),
    studioApiBase: cfg.get("studioApiBase", "http://127.0.0.1:1234/v1"),
    llamacppApiBase: cfg.get("llamacppApiBase", "http://127.0.0.1:8080/v1"),
    fim: {
      enabled: fim.enabled ?? true,
      endpoint: fim.endpoint ?? "auto",
      model: fim.model ?? "navi",
      maxTokens: fim.maxTokens ?? 96,
      temperature: fim.temperature ?? 0.1,
      stopTokens: fim.stopTokens ?? [
        "<|endoftext|>",
        "<|fim_pad|>",
        "<|file_separator|>"
      ],
      debounceMs: fim.debounceMs ?? 150,
      languages: fim.languages ?? [
        "asar",
        "65816-assembly",
        "assembly",
        "c",
        "cpp",
        "typescript",
        "javascript",
        "python",
        "markdown"
      ],
      contextPrefixChars: fim.contextPrefixChars ?? 2e3,
      contextSuffixChars: fim.contextSuffixChars ?? 1e3
    },
    chat: {
      defaultMode: chat.defaultMode ?? "",
      defaultRoute: chat.defaultRoute ?? ""
    }
  };
}
function resolveWorkspace(cfg) {
  if (cfg.workspace.trim()) {
    return cfg.workspace;
  }
  const folder = vscode2.workspace.workspaceFolders?.[0];
  return folder?.uri.fsPath;
}

// src/ipc/client.ts
var import_node_child_process = require("node:child_process");
var import_node_events = require("node:events");
var import_node_fs = require("node:fs");
var import_node_os = require("node:os");
var import_node_path = require("node:path");
var import_node_readline = require("node:readline");
var vscode3 = __toESM(require("vscode"));
var READY_TIMEOUT_MS = 3e4;
var Z3cliClient = class extends import_node_events.EventEmitter {
  constructor(opts) {
    super();
    this.opts = opts;
  }
  proc = null;
  rl = null;
  nextId = 1;
  pending = /* @__PURE__ */ new Map();
  ready = null;
  readyWaiters = [];
  restarts = 0;
  stopping = false;
  restartTimer = null;
  lastStderr = "";
  isRunning() {
    return this.proc !== null;
  }
  getReady() {
    return this.ready;
  }
  /** Build the process launch used to spawn z3cli --serve. */
  buildLaunch() {
    const { cfg } = this.opts;
    const trailing = ["--serve"];
    const workspace4 = this.opts.cwd ?? resolveWorkspace(cfg);
    if (workspace4)
      trailing.push("--workspace", workspace4);
    if (cfg.rom.trim())
      trailing.push("--rom", cfg.rom);
    if (cfg.chat.defaultMode.trim())
      trailing.push("--mode", cfg.chat.defaultMode);
    trailing.push(...cfg.extraArgs);
    if (cfg.serveCommand.length > 0) {
      const [executable, ...rest] = cfg.serveCommand;
      return {
        executable,
        args: [...rest, ...trailing],
        cwd: workspace4 ?? process.cwd()
      };
    }
    const moduleName = cfg.module || "z3cli";
    const checkoutPath = findCheckoutPath(cfg, workspace4);
    const cwd = checkoutPath ?? workspace4 ?? process.cwd();
    if (checkoutPath)
      log(`using z3cli checkout ${checkoutPath}`);
    return {
      executable: cfg.pythonPath,
      args: ["-m", moduleName, ...trailing],
      cwd
    };
  }
  start() {
    if (this.proc)
      return;
    this.stopping = false;
    this.lastStderr = "";
    const { executable, args, cwd } = this.buildLaunch();
    log(`spawn: ${executable} ${args.join(" ")} (cwd ${cwd})`);
    const proc = (0, import_node_child_process.spawn)(executable, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        Z3CLI_VSCODE: "1"
      },
      cwd
    });
    this.proc = proc;
    this.rl = (0, import_node_readline.createInterface)({ input: proc.stdout });
    this.rl.on("line", (line) => this.handleLine(line));
    proc.stderr?.on("data", (chunk) => {
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
      if (!String(err.message ?? "").startsWith("backend ready timed out")) {
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
  scheduleRestart() {
    const configuredMax = Math.floor(this.opts.cfg.maxRestarts);
    const maxRestarts = Number.isFinite(configuredMax) ? Math.max(0, configuredMax) : 8;
    if (maxRestarts > 0 && this.restarts >= maxRestarts) {
      log(`restart limit reached (${maxRestarts}); backend remains offline`);
      return;
    }
    this.restarts++;
    const delay = Math.min(15e3, 500 * 2 ** Math.min(this.restarts, 5));
    log(`restart in ${delay}ms (attempt ${this.restarts})`);
    if (this.restartTimer)
      clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.stopping)
        this.start();
    }, delay);
  }
  async stop() {
    this.stopping = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const proc = this.proc;
    if (!proc)
      return;
    try {
      await this.notify("shutdown");
    } catch {
    }
    proc.kill();
    this.rejectPending("Backend stopped");
    this.rejectReadyWaiters("Backend stopped");
  }
  /** Wait until the backend emits its first `ready` notification. */
  waitForReady(timeoutMs = READY_TIMEOUT_MS) {
    if (this.ready)
      return Promise.resolve(this.ready);
    return new Promise((resolve, reject) => {
      let waiter;
      const timer = setTimeout(() => {
        this.readyWaiters = this.readyWaiters.filter((w) => w !== waiter);
        reject(new Error(`backend ready timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      waiter = {
        resolve: (params) => {
          clearTimeout(timer);
          resolve(params);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
        timer
      };
      this.readyWaiters.push(waiter);
    });
  }
  handleLine(line) {
    const trimmed = line.trim();
    if (!trimmed)
      return;
    let parsed;
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
      this.deliverEvent(parsed);
    }
  }
  deliverResponse(msg) {
    const pending = this.pending.get(msg.id);
    if (!pending)
      return;
    this.pending.delete(msg.id);
    clearTimeout(pending.timer);
    if (msg.error) {
      pending.reject(new Error(msg.error.message));
    } else {
      pending.resolve(msg.result);
    }
  }
  deliverEvent(evt) {
    if (evt.method === "ready") {
      this.ready = evt.params;
      this.restarts = 0;
      const waiters = this.readyWaiters;
      this.readyWaiters = [];
      for (const w of waiters)
        w.resolve(this.ready);
    }
    this.emit("event", evt);
    this.emit(evt.method, evt.params);
  }
  rejectPending(reason) {
    for (const [, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(new Error(reason));
    }
    this.pending.clear();
  }
  rejectReadyWaiters(reason) {
    const waiters = this.readyWaiters;
    this.readyWaiters = [];
    for (const waiter of waiters) {
      clearTimeout(waiter.timer);
      waiter.reject(new Error(reason));
    }
  }
  request(method, params, timeoutMs = 48e4) {
    if (!this.proc?.stdin?.writable) {
      return Promise.reject(new Error("Backend not running"));
    }
    const id = this.nextId++;
    const req = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${method} timed out after ${Math.round(timeoutMs / 1e3)}s`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve,
        reject,
        timer
      });
      this.proc.stdin.write(JSON.stringify(req) + "\n");
    });
  }
  /** Send a JSON-RPC notification (no id, no response expected). */
  notify(method, params) {
    if (!this.proc?.stdin?.writable)
      return Promise.resolve();
    const payload = JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n";
    return new Promise((resolve) => {
      this.proc.stdin.write(payload, () => resolve());
    });
  }
  async runCommand(cmd, args = []) {
    return this.request("command", { cmd, args });
  }
  async chat(message, params = {}) {
    return this.request("chat", { message, ...params });
  }
  async cancel() {
    try {
      await this.notify("cancel");
    } catch (err) {
      logError("cancel", err);
    }
  }
};
function findCheckoutPath(cfg, workspace4) {
  const home = (0, import_node_os.homedir)();
  const candidates = [
    cfg.checkoutPath,
    process.env.Z3CLI_REPO_PATH,
    workspace4,
    (0, import_node_path.join)(home, "src/hobby/z3cli"),
    (0, import_node_path.join)(home, "src/lab/z3cli"),
    (0, import_node_path.join)(home, "src/z3cli")
  ];
  for (const candidate of candidates) {
    const dir = String(candidate ?? "").trim();
    if (dir && looksLikeCheckout(dir))
      return dir;
  }
  return void 0;
}
function looksLikeCheckout(dir) {
  return (0, import_node_fs.existsSync)((0, import_node_path.join)(dir, "z3cli.py")) && (0, import_node_fs.existsSync)((0, import_node_path.join)(dir, "src/app/__main__.py")) && (0, import_node_fs.existsSync)((0, import_node_path.join)(dir, "pyproject.toml"));
}

// src/status/bar.ts
var vscode4 = __toESM(require("vscode"));
var StatusBar = class {
  constructor(client2) {
    this.client = client2;
    this.root = vscode4.window.createStatusBarItem(vscode4.StatusBarAlignment.Left, 100);
    this.root.command = "z3cli.chat.open";
    this.root.text = "$(sparkle) z3cli starting\u2026";
    this.root.tooltip = "Open Z3CLI chat";
    this.root.show();
    this.route = vscode4.window.createStatusBarItem(vscode4.StatusBarAlignment.Left, 99);
    this.route.command = "z3cli.route.switch";
    this.route.text = "$(milestone) route \u2014";
    this.route.tooltip = "Switch z3cli route";
    this.route.show();
    this.cache = vscode4.window.createStatusBarItem(vscode4.StatusBarAlignment.Left, 98);
    this.cache.command = "z3cli.refresh";
    this.cache.text = "$(database) cache \u2014";
    this.cache.tooltip = "Anthropic prompt-cache hit rate (cache reads / cache total)";
    this.cache.hide();
    this.items = [this.root, this.route, this.cache];
    this.client.on("ready", (params) => this.applyReady(params));
    this.client.on("done", () => this.refreshFromReady());
    this.client.on("exit", () => this.markDown());
  }
  items;
  root;
  route;
  cache;
  applyReady(params) {
    const model = params.active_model || "\u2014";
    const backend = params.backend || "?";
    this.root.text = `$(sparkle) z3cli \xB7 ${model}`;
    this.root.tooltip = `backend ${backend} \xB7 mode ${params.mode}`;
    const route = pickRouteLabel(params);
    this.route.text = `$(milestone) ${route}`;
    this.route.tooltip = `Active route \u2014 click to switch`;
    this.updateCache(params);
  }
  refreshFromReady() {
    const ready = this.client.getReady();
    if (ready)
      this.updateCache(ready);
  }
  updateCache(params) {
    const reads = params.cache_read_tokens ?? 0;
    const creation = params.cache_creation_tokens ?? 0;
    const denominator = reads + creation;
    if (denominator <= 0) {
      this.cache.hide();
      return;
    }
    const rate = reads / denominator * 100;
    this.cache.text = `$(database) cache ${rate.toFixed(0)}%`;
    this.cache.tooltip = `cache reads ${reads} / total ${denominator}`;
    this.cache.show();
  }
  markDown() {
    this.root.text = "$(sparkle) z3cli offline";
    this.route.text = "$(milestone) route \u2014";
    this.cache.hide();
  }
  dispose() {
    for (const it of this.items)
      it.dispose();
  }
};
function pickRouteLabel(params) {
  if (params.studio_node)
    return params.studio_node;
  if (params.llamacpp_node)
    return params.llamacpp_node;
  if (params.backend === "studio" && params.studio_model)
    return params.studio_model;
  if (params.backend === "llamacpp" && params.llamacpp_model)
    return params.llamacpp_model;
  return params.backend;
}

// src/commands/register.ts
var vscode5 = __toESM(require("vscode"));

// src/commands/args.ts
function splitArgs(raw) {
  const tokens = [];
  let cur = "";
  let quote = null;
  let inToken = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        cur += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      inToken = true;
      continue;
    }
    if (/\s/.test(ch)) {
      if (inToken) {
        tokens.push(cur);
        cur = "";
        inToken = false;
      }
      continue;
    }
    cur += ch;
    inToken = true;
  }
  if (inToken)
    tokens.push(cur);
  return tokens;
}

// src/commands/register.ts
function registerCommands(context, client2, opts) {
  const reg = (id, handler) => {
    context.subscriptions.push(vscode5.commands.registerCommand(id, handler));
  };
  reg("z3cli.chat.open", async () => {
    await vscode5.commands.executeCommand("z3cli.chat.focus");
  });
  reg("z3cli.chat.send", async () => {
    const editor = vscode5.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
      vscode5.window.showInformationMessage("Z3CLI: select code to send first.");
      return;
    }
    const selection = editor.document.getText(editor.selection);
    const language = editor.document.languageId;
    const file = vscode5.workspace.asRelativePath(editor.document.uri);
    const message = `Selection from \`${file}\` (${language}):

\`\`\`${language}
${selection}
\`\`\`

What does this do? Any bugs or improvements?`;
    await vscode5.commands.executeCommand("z3cli.chat.focus");
    await client2.chat(message);
  });
  reg("z3cli.chat.clear", async () => {
    await runSlash(client2, "/reset", []);
  });
  reg("z3cli.route.list", async () => {
    const list = await fetchRouteList(client2);
    if (!list)
      return;
    const lines = list.routes.map((r) => `${r === list.active ? "\u2192" : " "} ${r}`);
    vscode5.window.showInformationMessage(`Routes (active: ${list.active}):
${lines.join("\n")}`);
  });
  reg("z3cli.route.switch", async () => {
    const list = await fetchRouteList(client2);
    if (!list || list.items.length === 0) {
      vscode5.window.showWarningMessage("Z3CLI: no routes reported by backend.");
      return;
    }
    const choice = await vscode5.window.showQuickPick(list.items, {
      placeHolder: `Pick a z3cli route (active: ${list.active})`,
      matchOnDescription: true
    });
    if (!choice)
      return;
    try {
      await client2.request("route/select", { route: choice.label });
    } catch (err) {
      logError("route/select", err);
      vscode5.window.showErrorMessage(`Z3CLI: route/select failed: ${err.message}`);
      return;
    }
    opts.routes.refresh();
  });
  reg("z3cli.route.smoke", async () => {
    const list = await fetchRouteList(client2);
    const choice = list && list.items.length ? await vscode5.window.showQuickPick(list.items, { placeHolder: "Smoke which route?" }) : void 0;
    try {
      const params = {};
      if (choice)
        params.route = choice.label;
      const result = await client2.request("route/probe", params);
      const ok = result?.ok ? "ok" : "FAILED";
      const route = result?.route ?? choice?.label ?? "(active)";
      vscode5.window.showInformationMessage(`Z3CLI smoke ${route}: ${ok} (${result?.durationMs ?? 0}ms)`);
    } catch (err) {
      logError("route/probe", err);
      vscode5.window.showErrorMessage(`Z3CLI: route/probe failed: ${err.message}`);
    }
  });
  reg("z3cli.model.pick", async () => {
    const ready = client2.getReady();
    if (!ready) {
      vscode5.window.showWarningMessage("Z3CLI: backend not ready yet.");
      return;
    }
    const items = (ready.models ?? []).filter((m) => m.selectable !== false).map((m) => ({
      label: m.name,
      description: m.role,
      detail: m.description ?? m.model_id,
      picked: m.name === ready.active_model
    }));
    const choice = await vscode5.window.showQuickPick(items, {
      placeHolder: `Active: ${ready.active_model}`
    });
    if (!choice)
      return;
    await runSlash(client2, "/model", [choice.label]);
    opts.routes.refresh();
  });
  reg("z3cli.model.switch", async (alias) => {
    if (typeof alias !== "string")
      return;
    await runSlash(client2, "/model", [alias]);
    opts.routes.refresh();
  });
  reg("z3cli.model.load", async () => {
    const alias = await vscode5.window.showInputBox({ prompt: "Model alias to load" });
    if (!alias)
      return;
    await runSlash(client2, "/load", [alias]);
  });
  reg("z3cli.model.unload", async () => {
    const alias = await vscode5.window.showInputBox({
      prompt: "Model alias to unload (use 'all' for all)"
    });
    if (!alias)
      return;
    await runSlash(client2, "/unload", [alias]);
  });
  reg("z3cli.model.loaded", async () => runSlash(client2, "/loaded", []));
  reg("z3cli.mode.pick", async () => {
    const choices = ["manual", "oracle", "orchestrator", "broadcast"].map((m) => ({ label: m }));
    const ready = client2.getReady();
    const choice = await vscode5.window.showQuickPick(choices, {
      placeHolder: ready ? `Active mode: ${ready.mode}` : "Pick mode"
    });
    if (!choice)
      return;
    await runSlash(client2, "/mode", [choice.label]);
  });
  reg("z3cli.specialist.pick", async () => {
    const choices = ["din", "navi", "nayru"].map((s) => ({ label: s }));
    const choice = await vscode5.window.showQuickPick(choices, { placeHolder: "Pick specialist" });
    if (!choice)
      return;
    await runSlash(client2, "/specialist", [choice.label]);
  });
  reg("z3cli.workspace.set", async () => {
    const folders = vscode5.workspace.workspaceFolders ?? [];
    const items = folders.map((f) => ({ label: f.name, description: f.uri.fsPath }));
    items.push({ label: "Browse\u2026", description: "" });
    const choice = await vscode5.window.showQuickPick(items, { placeHolder: "Pick workspace" });
    if (!choice)
      return;
    let path = choice.description;
    if (choice.label === "Browse\u2026") {
      const picked = await vscode5.window.showOpenDialog({ canSelectFolders: true, canSelectMany: false });
      path = picked?.[0]?.fsPath ?? "";
    }
    if (!path)
      return;
    await runSlash(client2, "/workspace", [path]);
  });
  reg("z3cli.rom.set", async () => {
    const picked = await vscode5.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { ROM: ["sfc", "smc"] }
    });
    const path = picked?.[0]?.fsPath;
    if (!path)
      return;
    await runSlash(client2, "/rom", [path]);
  });
  reg("z3cli.focus.set", async () => {
    const editor = vscode5.window.activeTextEditor;
    if (!editor) {
      vscode5.window.showInformationMessage("Z3CLI: open a file first.");
      return;
    }
    await runSlash(client2, "/focus", [editor.document.uri.fsPath]);
  });
  reg("z3cli.focus.clear", async () => runSlash(client2, "/focus", ["clear"]));
  reg("z3cli.tools.toggle", async () => {
    const ready = client2.getReady();
    const next = ready?.tools_enabled ? "off" : "on";
    await runSlash(client2, "/tools", [next]);
  });
  reg("z3cli.tools.toggleWrite", async () => {
    const ready = client2.getReady();
    const next = ready?.tools_write ? "off" : "on";
    await runSlash(client2, "/tools-write", [next]);
  });
  reg("z3cli.verifyHooks.toggle", async () => {
    const ready = client2.getReady();
    const next = ready?.verify_hooks ? "off" : "on";
    await runSlash(client2, "/verify-hooks", [next]);
  });
  reg("z3cli.compact", async () => runSlash(client2, "/compact", []));
  reg("z3cli.reset", async () => {
    const which = await vscode5.window.showQuickPick(["this model", "all"], {
      placeHolder: "Reset history scope"
    });
    if (!which)
      return;
    await runSlash(client2, "/reset", which === "all" ? ["all"] : []);
  });
  reg("z3cli.session.save", async () => runSlash(client2, "/save", []));
  reg("z3cli.session.list", async () => runSlash(client2, "/sessions", []));
  reg("z3cli.session.resume", async () => {
    const name = await vscode5.window.showInputBox({ prompt: "Session name to resume" });
    if (!name)
      return;
    await runSlash(client2, "/resume", [name]);
  });
  reg("z3cli.export.training", async () => {
    const out = await vscode5.window.showInputBox({ prompt: "Output JSONL path (blank for default)" });
    await runSlash(client2, "/export-training", out ? [out] : []);
  });
  reg("z3cli.shell.run", async () => {
    const cmd = await vscode5.window.showInputBox({ prompt: "Shell command (persistent session)" });
    if (!cmd)
      return;
    await runSlash(client2, "/shell", [cmd]);
  });
  reg("z3cli.smoke", async () => runSlash(client2, "/smoke", []));
  reg("z3cli.refresh", async () => {
    opts.routes.refresh();
    opts.commands.refresh();
  });
  reg("z3cli.help", async () => runSlash(client2, "/help", []));
  reg("z3cli.fim.trigger", async () => {
    await vscode5.commands.executeCommand("editor.action.inlineSuggest.trigger");
  });
  reg("z3cli.fim.toggle", async () => {
    const cfg = vscode5.workspace.getConfiguration("z3cli.fim");
    const next = !cfg.get("enabled", true);
    await cfg.update("enabled", next, vscode5.ConfigurationTarget.Workspace);
    vscode5.window.showInformationMessage(`Z3CLI FIM ${next ? "enabled" : "disabled"} (reload window).`);
  });
  reg("z3cli.run.slash", async (entry) => {
    if (!entry || typeof entry !== "object")
      return;
    const command = entry;
    const args = command.args ? await promptForArgs(command) : [];
    if (args === void 0)
      return;
    await runSlash(client2, command.name, args);
  });
}
async function runSlash(client2, slash, args) {
  try {
    await client2.runCommand(slash, args);
  } catch (err) {
    logError(`${slash} ${args.join(" ")}`, err);
    vscode5.window.showErrorMessage(`Z3CLI: ${slash} failed: ${err.message}`);
  }
}
async function promptForArgs(entry) {
  const raw = await vscode5.window.showInputBox({
    prompt: `${entry.name} ${entry.args}`,
    placeHolder: entry.description
  });
  if (raw === void 0)
    return void 0;
  if (!raw.trim())
    return [];
  return splitArgs(raw);
}
async function fetchRouteList(client2) {
  try {
    const result = await client2.request("route/list", { includeHidden: false });
    const items = (result?.routes ?? []).filter((r) => typeof r.name === "string" && r.name.length > 0).map((r) => ({
      label: String(r.name),
      description: stringOrUndef(r.backend) ?? stringOrUndef(r.model),
      detail: stringOrUndef(r.displayName) ?? stringOrUndef(r.detail)
    }));
    return {
      active: String(result?.activeRoute ?? ""),
      routes: items.map((i) => i.label),
      items
    };
  } catch (err) {
    logError("route/list", err);
    vscode5.window.showErrorMessage(`Z3CLI: route/list failed: ${err.message}`);
    return null;
  }
}
function stringOrUndef(value) {
  return typeof value === "string" && value.length > 0 ? value : void 0;
}

// src/commands/tree.ts
var vscode6 = __toESM(require("vscode"));

// src/commands/command_catalog.json
var command_catalog_default = {
  welcomeHints: [
    "/help",
    "/oracle-tips",
    "/resume",
    "@file",
    "#room:0x45",
    "!bash",
    "Ctrl+P palette"
  ],
  commands: [
    { name: "/help", args: "", description: "Show available commands", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "help commands", paletteLabel: "Help" },
    { name: "/oracle-tips", args: "", description: "Show a short cheat sheet for talking to local Oracle models", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "oracle tips prompt prompting local ai help", paletteLabel: "Oracle Prompt Tips", paletteDescription: "Show prompt tips for local Oracle models" },
    { name: "/workspace", args: "<path>", description: "Change workspace", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "workspace project root" },
    { name: "/rom", args: "<path|none>", description: "Change ROM target", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "rom target" },
    { name: "/status", args: "", description: "Connection and state info", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "status info runtime", paletteLabel: "Status", paletteDescription: "Show current runtime state" },
    { name: "/save", args: "", description: "Show session file path", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "save session path" },
    { name: "/sessions", args: "", description: "List saved sessions", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "resume sessions history", paletteLabel: "Sessions", paletteDescription: "Browse saved sessions" },
    { name: "/resume", args: "<name>", description: "Resume a saved session", group: "quest", groupTitle: "Quest & Navigation", groupSymbol: "\u25CE", aliases: "resume restore session", paletteLabel: "Resume Session Picker", paletteDescription: "Open session search" },
    { name: "/backend", args: "[name]", description: "Show or set backend", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "backend studio llamacpp" },
    { name: "/route", args: "[list [advanced|--all]|target|smoke [target]|health [target]|preview <prompt>]", description: "Select, inspect, or probe inference routes", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "route routes home vast oracle-pro-5090 oracle-pro-ssh switch target advanced" },
    { name: "/use", args: "[target]", description: "Legacy alias for /route <target>", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "use home vast oracle-pro switch target" },
    { name: "/backends", args: "", description: "List available backends", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "backend list" },
    { name: "/backend-status", args: "", description: "Show backend status", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "backend health" },
    { name: "/smoke", args: "[target]", description: "Probe the active or named model route with a tiny completion", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "doctor health smoke probe oracle-pro-ssh home-ssh" },
    { name: "/studio-nodes", args: "", description: "List named LM Studio inference nodes", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "studio nodes inference nodes" },
    { name: "/studio-node", args: "[name]", description: "Show or switch the active LM Studio node", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "studio node switch inference node" },
    { name: "/llamacpp-nodes", args: "", description: "List named llama.cpp inference nodes", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "llama nodes inference nodes" },
    { name: "/llamacpp-node", args: "[name]", description: "Show or switch the active llama.cpp node", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "llama node switch inference node" },
    { name: "/model", args: "<name>", description: "Switch active model", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "model switch oracle", paletteLabel: "Model Picker", paletteDescription: "Choose the active model" },
    { name: "/models", args: "[list|catalog|loaded|routes [advanced|--all]]", description: "Browse model catalog, loaded models, and linked routes", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "model list catalog loaded routes advanced" },
    { name: "/mode", args: "<name>", description: "Set routing mode", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "mode route routing", paletteLabel: "Mode Picker", paletteDescription: "Choose routing mode" },
    { name: "/modes", args: "", description: "List routing modes", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "routing modes" },
    { name: "/orchestrator", args: "[name|auto]", description: "Show or set orchestrator planner", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "orchestrator planner cloud", paletteLabel: "Orchestrator", paletteDescription: "Show or set the cloud planner" },
    { name: "/specialist", args: "<name>", description: "Switch to a specialist in manual mode", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "specialist manual" },
    { name: "/broadcast", args: "<a,b,c>", description: "Set broadcast models", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "broadcast fanout" },
    { name: "/model-manager", args: "", description: "Open model manager panel", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "model manager loaded memory unload", paletteLabel: "Model Manager", paletteDescription: "Inspect and manage loaded models" },
    { name: "/load", args: "[name]", description: "Load model in LM Studio", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "load lm studio" },
    { name: "/unload", args: "[name|all]", description: "Unload model from LM Studio", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "unload lm studio memory" },
    { name: "/loaded", args: "", description: "List loaded API models", group: "models", groupTitle: "Models & Routing", groupSymbol: "\u2694", aliases: "loaded models" },
    { name: "/servers", args: "", description: "Tool server info", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "servers tools" },
    { name: "/tools", args: "<on|off>", description: "Toggle tool use", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "tools enable disable" },
    { name: "/tools-write", args: "<on|off>", description: "Toggle tool write access", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "tools write access" },
    { name: "/verify-hooks", args: "<on|off>", description: "Toggle automatic verification", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "verify hooks" },
    { name: "/lsp-context", args: "[mode]", description: "Show or set z3lsp prompt context", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "lsp context rich balanced" },
    { name: "/permissions", args: "[clear]", description: "Show or clear sticky tool rules", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "permissions sticky rules", paletteLabel: "Permissions", paletteDescription: "Show sticky tool rules" },
    { name: "/focus", args: "<path|clear>", description: "Load file into system prompt", group: "tools", groupTitle: "Tools & Context", groupSymbol: "\u2726", aliases: "focus file context" },
    { name: "/reset", args: "[model|all]", description: "Clear history", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "reset clear history" },
    { name: "/stats", args: "", description: "Session statistics", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "stats metrics" },
    { name: "/compact", args: "[model]", description: "Compress history (lossy)", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "compact summarize history" },
    { name: "/tool-timings", args: "[count]", description: "Show recent tool invocation latencies", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "tool timings latency" },
    { name: "/export-training", args: "[out] [model] [--include-thinking]", description: "Export session to training JSONL", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "export training jsonl" },
    { name: "/shell", args: "[command]", description: "Run a persistent shell command", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "shell bash" },
    { name: "/shell-log", args: "[count]", description: "Show recent shell commands", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "shell history" },
    { name: "/shell-reset", args: "", description: "Reset the persistent shell session", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "shell reset" },
    { name: "/settings", args: "[key value]", description: "Open UI settings panel", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "settings ui", paletteLabel: "Settings", paletteDescription: "Open UI settings" },
    { name: "/exit", args: "", description: "Quit z3cli", group: "session", groupTitle: "Session & Shell", groupSymbol: "\u25C8", aliases: "exit quit" }
  ]
};

// src/commands/catalog.ts
var catalog = command_catalog_default;
var COMMAND_CATALOG = catalog.commands;
var WELCOME_HINTS = catalog.welcomeHints;
var COMMAND_GROUPS = (() => {
  const groups = /* @__PURE__ */ new Map();
  for (const entry of COMMAND_CATALOG) {
    const existing = groups.get(entry.group);
    if (existing) {
      existing.entries.push(entry);
    } else {
      groups.set(entry.group, {
        key: entry.group,
        title: entry.groupTitle,
        symbol: entry.groupSymbol,
        entries: [entry]
      });
    }
  }
  return Array.from(groups.values());
})();

// src/commands/tree.ts
function toItem(node) {
  const item = new vscode6.TreeItem(
    node.label,
    node.collapsibleState ?? (node.children?.length ? vscode6.TreeItemCollapsibleState.Collapsed : vscode6.TreeItemCollapsibleState.None)
  );
  if (node.description)
    item.description = node.description;
  if (node.tooltip)
    item.tooltip = node.tooltip;
  if (node.contextValue)
    item.contextValue = node.contextValue;
  if (node.iconId)
    item.iconPath = new vscode6.ThemeIcon(node.iconId);
  if (node.command)
    item.command = node.command;
  return item;
}
var CommandsTreeProvider = class {
  emitter = new vscode6.EventEmitter();
  onDidChangeTreeData = this.emitter.event;
  nodes = [];
  constructor() {
    this.nodes = COMMAND_GROUPS.map((group) => ({
      label: `${group.symbol} ${group.title}`,
      contextValue: "z3cli.group",
      iconId: groupIcon(group.key),
      collapsibleState: vscode6.TreeItemCollapsibleState.Collapsed,
      children: group.entries.map((entry) => ({
        label: entry.paletteLabel ?? entry.name,
        description: entry.args || void 0,
        tooltip: entry.description,
        contextValue: "z3cli.commandLeaf",
        iconId: "play",
        command: {
          command: "z3cli.run.slash",
          title: entry.description,
          arguments: [entry]
        }
      }))
    }));
  }
  refresh() {
    this.emitter.fire(void 0);
  }
  getTreeItem(node) {
    return toItem(node);
  }
  getChildren(node) {
    if (!node)
      return this.nodes;
    return node.children ?? [];
  }
};
var RoutesTreeProvider = class {
  constructor(client2) {
    this.client = client2;
    this.client.on("ready", () => this.refresh());
    this.client.on("done", () => this.refresh());
  }
  emitter = new vscode6.EventEmitter();
  onDidChangeTreeData = this.emitter.event;
  refresh() {
    this.emitter.fire(void 0);
  }
  getTreeItem(node) {
    return toItem(node);
  }
  getChildren(node) {
    if (node?.children)
      return node.children;
    if (node)
      return [];
    return this.buildRoot();
  }
  buildRoot() {
    const ready = this.client.getReady();
    if (!ready) {
      return [{
        label: "Waiting for backend\u2026",
        iconId: "loading~spin"
      }];
    }
    return [
      summary(ready),
      models(ready)
    ];
  }
};
function summary(ready) {
  return {
    label: "Active",
    collapsibleState: vscode6.TreeItemCollapsibleState.Expanded,
    iconId: "milestone",
    children: [
      {
        label: "Backend",
        description: ready.backend,
        iconId: "server"
      },
      {
        label: "Model",
        description: ready.active_model,
        iconId: "circuit-board",
        command: {
          command: "z3cli.model.pick",
          title: "Switch model"
        }
      },
      {
        label: "Mode",
        description: ready.mode,
        iconId: "settings",
        command: {
          command: "z3cli.mode.pick",
          title: "Switch mode"
        }
      },
      {
        label: "Workspace",
        description: ready.workspace,
        iconId: "folder",
        command: {
          command: "z3cli.workspace.set",
          title: "Set workspace"
        }
      }
    ]
  };
}
function models(ready) {
  const items = (ready.models ?? []).map((model) => ({
    label: model.name,
    description: model.role,
    tooltip: model.description ?? model.model_id,
    iconId: model.loaded ? "check" : "dash",
    command: {
      command: "z3cli.model.switch",
      title: `Switch to ${model.name}`,
      arguments: [model.name]
    }
  }));
  return {
    label: "Models",
    collapsibleState: vscode6.TreeItemCollapsibleState.Collapsed,
    iconId: "list-tree",
    children: items.length ? items : [{ label: "No models reported", iconId: "warning" }]
  };
}
function groupIcon(key) {
  switch (key) {
    case "quest":
      return "compass";
    case "models":
      return "circuit-board";
    case "tools":
      return "tools";
    case "session":
      return "history";
    default:
      return "list-unordered";
  }
}

// src/chat/panel.ts
var vscode7 = __toESM(require("vscode"));

// src/chat/html.ts
var CHAT_HTML = (
  /* html */
  `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';" />
  <style>
    :root { color-scheme: light dark; }
    html, body { height: 100%; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      display: flex;
      flex-direction: column;
    }
    header {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem 0.6rem;
      padding: 0.5rem 0.75rem;
      border-bottom: 1px solid var(--vscode-panel-border);
      background: var(--vscode-editor-background);
    }
    header button {
      font: inherit;
      background: var(--vscode-button-secondaryBackground, transparent);
      color: var(--vscode-foreground);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 3px;
      padding: 2px 6px;
      cursor: pointer;
    }
    header button:hover { background: var(--vscode-button-hoverBackground); }
    #status {
      flex-grow: 1;
      font-size: 0.85em;
      opacity: 0.85;
      align-self: center;
    }
    #transcript {
      flex: 1;
      overflow-y: auto;
      padding: 0.5rem 0.75rem 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .turn {
      border-left: 3px solid transparent;
      padding: 0.25rem 0.5rem;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .turn.user { border-color: var(--vscode-charts-blue, #4da3ff); }
    .turn.assistant { border-color: var(--vscode-charts-green, #6dbf73); }
    .turn.system { border-color: var(--vscode-charts-orange, #d8a657); opacity: 0.85; }
    .turn.tool { border-color: var(--vscode-charts-purple, #b48ead); font-family: var(--vscode-editor-font-family); font-size: 0.85em; }
    .turn header {
      background: transparent;
      border: none;
      padding: 0;
      margin: 0 0 0.15rem 0;
      font-size: 0.75em;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      opacity: 0.7;
    }
    .thinking {
      margin-top: 0.35rem;
      font-style: italic;
      opacity: 0.7;
      font-size: 0.9em;
      border-left: 2px dotted var(--vscode-panel-border);
      padding-left: 0.5rem;
    }
    .toolblock {
      margin-top: 0.35rem;
      border: 1px dashed var(--vscode-panel-border);
      border-radius: 3px;
      padding: 0.25rem 0.4rem;
      font-family: var(--vscode-editor-font-family);
      font-size: 0.85em;
    }
    .toolblock summary { cursor: pointer; }
    .tool-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-top: 0.4rem;
    }
    .tool-actions button {
      font: inherit;
      background: var(--vscode-button-secondaryBackground, transparent);
      color: var(--vscode-foreground);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 3px;
      padding: 0.2rem 0.5rem;
      cursor: pointer;
    }
    .tool-actions button.primary {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
    }
    .tool-actions button.danger {
      color: var(--vscode-errorForeground, var(--vscode-foreground));
    }
    .tool-actions button:disabled { opacity: 0.45; cursor: not-allowed; }
    .review-diff {
      max-height: 14rem;
      overflow: auto;
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 3px;
      padding: 0.35rem;
    }
    .subagent {
      margin-top: 0.35rem;
      border: 1px solid var(--vscode-panel-border);
      border-radius: 3px;
      padding: 0.25rem 0.4rem;
      background: rgba(127, 127, 127, 0.06);
    }
    .subagent header { font-weight: bold; opacity: 0.9; }
    .compact-banner {
      align-self: center;
      font-size: 0.8em;
      opacity: 0.7;
      border: 1px dotted var(--vscode-panel-border);
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
    }
    footer {
      border-top: 1px solid var(--vscode-panel-border);
      padding: 0.5rem 0.75rem;
      background: var(--vscode-editor-background);
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }
    textarea {
      font: inherit;
      width: 100%;
      min-height: 3.5rem;
      max-height: 12rem;
      resize: vertical;
      box-sizing: border-box;
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, var(--vscode-panel-border));
      border-radius: 3px;
      padding: 0.4rem;
    }
    .row {
      display: flex;
      gap: 0.4rem;
      align-items: center;
    }
    .row .grow { flex: 1; }
    .row button {
      font: inherit;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 3px;
      padding: 0.3rem 0.7rem;
      cursor: pointer;
    }
    .row button.secondary {
      background: var(--vscode-button-secondaryBackground, transparent);
      color: var(--vscode-foreground);
      border: 1px solid var(--vscode-panel-border);
    }
    .row button:disabled { opacity: 0.4; cursor: not-allowed; }
    .hint {
      font-size: 0.8em;
      opacity: 0.6;
    }
  </style>
</head>
<body>
  <header>
    <button id="modelBtn" title="Switch model">model: \u2026</button>
    <button id="modeBtn" title="Switch mode">mode: \u2026</button>
    <button id="routeBtn" title="Switch route">route: \u2026</button>
    <span id="status"></span>
  </header>
  <div id="transcript"></div>
  <footer>
    <textarea id="input" placeholder="Talk to Oracle\u2026  Use @file, #room:0x45, !shell, /slash"></textarea>
    <div class="row">
      <span class="hint grow">Enter to send \xB7 Shift+Enter newline \xB7 Esc cancel</span>
      <button id="cancelBtn" class="secondary" disabled>Cancel</button>
      <button id="sendBtn">Send</button>
    </div>
  </footer>
  <script>
    const vscode = acquireVsCodeApi();
    const transcript = document.getElementById("transcript");
    const input = document.getElementById("input");
    const sendBtn = document.getElementById("sendBtn");
    const cancelBtn = document.getElementById("cancelBtn");
    const modelBtn = document.getElementById("modelBtn");
    const modeBtn = document.getElementById("modeBtn");
    const routeBtn = document.getElementById("routeBtn");
    const status = document.getElementById("status");

    let inFlight = false;
    let active = null; // streaming assistant turn
    const subagents = new Map();

    function el(tag, cls, text) {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    function ensureActiveAssistant() {
      if (active) return active;
      const turn = el("div", "turn assistant");
      const head = el("header", null, "assistant");
      const body = el("div", "body");
      const thinking = el("div", "thinking");
      thinking.style.display = "none";
      turn.append(head, body, thinking);
      transcript.append(turn);
      active = { node: turn, body, thinking, tools: new Map() };
      scroll();
      return active;
    }

    function scroll() {
      transcript.scrollTop = transcript.scrollHeight;
    }

    function addTurn(role, content) {
      const turn = el("div", "turn " + role);
      turn.append(el("header", null, role));
      turn.append(el("div", "body", content));
      transcript.append(turn);
      scroll();
    }

    function clearActive() {
      active = null;
    }

    function onText(p) {
      const t = ensureActiveAssistant();
      t.body.append(document.createTextNode(p.delta));
      scroll();
    }

    function onThinking(p) {
      const t = ensureActiveAssistant();
      t.thinking.style.display = "";
      t.thinking.append(document.createTextNode(p.delta));
      scroll();
    }

    function onToolCall(p) {
      const t = ensureActiveAssistant();
      const block = el("details", "toolblock");
      const summary = el("summary", null, "tool: " + (p.name || "?") + " (" + (p.server || "") + ")");
      block.append(summary);
      const args = el("pre", null, p.arguments || "");
      block.append(args);
      const result = el("pre", null, "");
      result.style.opacity = "0.8";
      block.append(result);
      t.node.append(block);
      const id = p.call_id || p.name;
      t.tools.set(id, { result });
      scroll();
    }

    function onToolResult(p) {
      if (!active) return;
      const id = p.call_id || p.name;
      const entry = active.tools.get(id);
      if (entry) entry.result.textContent = p.result || "";
      scroll();
    }

    function disableActionButtons(container) {
      for (const button of container.querySelectorAll("button")) {
        button.disabled = true;
      }
    }

    function actionButton(label, className, cmd, args, container) {
      const button = el("button", className, label);
      button.addEventListener("click", () => {
        disableActionButtons(container);
        vscode.postMessage({ type: "command", cmd, args });
      });
      return button;
    }

    function onToolPermission(p) {
      const turn = el("div", "turn system");
      turn.append(el("header", null, "tool permission"));
      const body = el("div", "body");
      const title = (p.server || "tool") + ":" + (p.name || "?");
      body.append(el("div", null, p.reason ? title + " \xB7 " + p.reason : title));
      if (p.arguments) {
        const args = el("pre", null, p.arguments);
        args.className = "review-diff";
        body.append(args);
      }
      const actions = el("div", "tool-actions");
      actions.append(
        actionButton("Allow once", "primary", "tool/decision", ["allow-once"], actions),
        actionButton("Allow session", "", "tool/decision", ["allow-session"], actions),
        actionButton("Deny", "danger", "tool/decision", ["deny-once"], actions),
      );
      body.append(actions);
      turn.append(body);
      transcript.append(turn);
      scroll();
    }

    function onToolReview(p) {
      const turn = el("div", "turn system");
      turn.append(el("header", null, "tool review"));
      const body = el("div", "body");
      body.append(el("div", null, p.summary || ((p.server || "tool") + ":" + (p.name || "?"))));
      if (Array.isArray(p.paths) && p.paths.length) {
        body.append(el("div", null, "paths: " + p.paths.join(", ")));
      }
      if (Array.isArray(p.verification_commands) && p.verification_commands.length) {
        body.append(el("div", null, "verify: " + p.verification_commands.join(" && ")));
      }
      if (Array.isArray(p.diff_lines) && p.diff_lines.length) {
        const diff = el("pre", "review-diff", p.diff_lines.join("\\n") + (p.omitted ? "\\n\u2026 " + p.omitted + " more lines" : ""));
        body.append(diff);
      }
      const actions = el("div", "tool-actions");
      actions.append(
        actionButton("Accept", "primary", "tool/review", [p.review_id, "accept"], actions),
        actionButton("Reject", "danger", "tool/review", [p.review_id, "reject"], actions),
      );
      body.append(actions);
      turn.append(body);
      transcript.append(turn);
      scroll();
    }

    function onMessage(p) {
      if (p.role === "user") {
        let content = p.content || "";
        if (Array.isArray(p.attachments) && p.attachments.length) {
          content += "\\n\\nattachments: " + p.attachments.map(a => a.path).join(", ");
        }
        addTurn("user", content);
      } else if (p.role === "system") {
        addTurn("system", p.content || "");
      } else if (p.role === "tool") {
        addTurn("tool", (p.tool_name || "tool") + ": " + (p.content || ""));
      }
    }

    function onDone(p) {
      inFlight = false;
      sendBtn.disabled = false;
      cancelBtn.disabled = true;
      const ms = p.total_tokens != null ? p.total_tokens + " tokens" : "";
      const cache = p.cache_read_tokens
        ? " \xB7 cache " + p.cache_read_tokens + "/" + ((p.cache_read_tokens + (p.cache_creation_tokens || 0))) : "";
      status.textContent = ms ? (ms + cache) : "";
      clearActive();
    }

    function onError(p) {
      addTurn("system", "error: " + (p.message || ""));
      inFlight = false;
      sendBtn.disabled = false;
      cancelBtn.disabled = true;
      clearActive();
    }

    function onCompacted(p) {
      const banner = el("div", "compact-banner",
        "compacted " + p.replaced + " turns \xB7 " + p.tokens_before + " \u2192 " + p.tokens_after + " tokens");
      transcript.append(banner);
      scroll();
    }

    function onSubagentStart(p) {
      const node = el("div", "subagent");
      node.append(el("header", null, "subagent: " + p.name + " (" + p.model + ")"));
      const body = el("div", "body");
      node.append(body);
      const t = ensureActiveAssistant();
      t.node.append(node);
      subagents.set(p.id, { body, tools: new Map() });
      scroll();
    }

    function onSubagentText(p) {
      const entry = subagents.get(p.id);
      if (entry) {
        entry.body.append(document.createTextNode(p.delta));
        scroll();
      }
    }

    function onSubagentThinking(p) {
      const entry = subagents.get(p.id);
      if (entry) {
        if (!entry.thinking) {
          entry.thinking = el("div", "thinking");
          entry.body.append(entry.thinking);
        }
        entry.thinking.append(document.createTextNode(p.delta));
        scroll();
      }
    }

    function onSubagentToolCall(p) {
      const entry = subagents.get(p.id);
      if (!entry) return;
      const block = el("details", "toolblock");
      const summary = el("summary", null, "tool: " + (p.name || "?") + " (" + (p.server || "") + ")");
      block.append(summary);
      block.append(el("pre", null, p.arguments || ""));
      const result = el("pre", null, "");
      result.style.opacity = "0.8";
      block.append(result);
      entry.body.append(block);
      entry.tools.set(p.call_id || p.name, { result });
      scroll();
    }

    function onSubagentToolResult(p) {
      const entry = subagents.get(p.id);
      if (!entry) return;
      const tool = entry.tools.get(p.call_id || p.name);
      if (tool) {
        tool.result.textContent = p.result || "";
      } else {
        entry.body.append(el("pre", "toolblock", (p.name || "tool") + ": " + (p.result || "")));
      }
      scroll();
    }

    function onSubagentDone(p) {
      const entry = subagents.get(p.id);
      if (entry) {
        const footer = el("div", "hint",
          "tokens " + (p.prompt_tokens + p.completion_tokens) + (p.error ? " \xB7 error: " + p.error : ""));
        entry.body.append(footer);
        scroll();
      }
    }

    function onSubagentError(p) {
      const entry = subagents.get(p.id);
      if (entry) {
        entry.body.append(el("div", "hint", "error: " + (p.message || "")));
      } else {
        addTurn("system", "subagent error: " + (p.message || ""));
      }
      scroll();
    }

    function setReady(p) {
      modelBtn.textContent = "model: " + (p.active_model || "\u2014");
      modeBtn.textContent = "mode: " + (p.mode || "\u2014");
      const route = p.studio_node || p.llamacpp_node || p.backend || "\u2014";
      routeBtn.textContent = "route: " + route;
    }

    window.addEventListener("message", (event) => {
      const msg = event.data;
      switch (msg.type) {
        case "ready": setReady(msg.payload); break;
        case "text": onText(msg.payload); break;
        case "thinking": onThinking(msg.payload); break;
        case "tool_call": onToolCall(msg.payload); break;
        case "tool_result": onToolResult(msg.payload); break;
        case "tool/permission_request": onToolPermission(msg.payload); break;
        case "tool/review_request": onToolReview(msg.payload); break;
        case "message": onMessage(msg.payload); break;
        case "done": onDone(msg.payload); break;
        case "error": onError(msg.payload); break;
        case "context/compacted": onCompacted(msg.payload); break;
        case "subagent/start": onSubagentStart(msg.payload); break;
        case "subagent/text": onSubagentText(msg.payload); break;
        case "subagent/thinking": onSubagentThinking(msg.payload); break;
        case "subagent/tool_call": onSubagentToolCall(msg.payload); break;
        case "subagent/tool_result": onSubagentToolResult(msg.payload); break;
        case "subagent/done": onSubagentDone(msg.payload); break;
        case "subagent/error": onSubagentError(msg.payload); break;
      }
    });

    function sendMessage() {
      const text = input.value.trim();
      if (!text || inFlight) return;
      const isCommand = text.startsWith("/");
      if (!isCommand) {
        inFlight = true;
        sendBtn.disabled = true;
        cancelBtn.disabled = false;
      }
      vscode.postMessage({ type: "send", message: text });
      input.value = "";
    }

    sendBtn.addEventListener("click", sendMessage);
    cancelBtn.addEventListener("click", () => vscode.postMessage({ type: "cancel" }));
    modelBtn.addEventListener("click", () => vscode.postMessage({ type: "modelPick" }));
    modeBtn.addEventListener("click", () => vscode.postMessage({ type: "modePick" }));
    routeBtn.addEventListener("click", () => vscode.postMessage({ type: "routePick" }));

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        vscode.postMessage({ type: "cancel" });
      }
    });

    vscode.postMessage({ type: "ready" });
  </script>
</body>
</html>`
);

// src/chat/panel.ts
var ChatPanelProvider = class {
  constructor(_context, client2) {
    this.client = client2;
    this.wireClient();
  }
  view = null;
  subscriptions = [];
  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = CHAT_HTML;
    view.webview.onDidReceiveMessage((msg) => this.handleInbound(msg));
    const ready = this.client.getReady();
    if (ready)
      this.post({ type: "ready", payload: ready });
  }
  wireClient() {
    const on = (event, fn) => {
      this.client.on(event, fn);
      this.subscriptions.push(new vscode7.Disposable(() => this.client.off(event, fn)));
    };
    on("ready", (p) => this.post({ type: "ready", payload: p }));
    on("text", (p) => this.post({ type: "text", payload: p }));
    on("thinking", (p) => this.post({ type: "thinking", payload: p }));
    on("tool_call", (p) => this.post({ type: "tool_call", payload: p }));
    on("tool_result", (p) => this.post({ type: "tool_result", payload: p }));
    on("tool/permission_request", (p) => this.post({ type: "tool/permission_request", payload: p }));
    on("tool/review_request", (p) => this.post({ type: "tool/review_request", payload: p }));
    on("message", (p) => this.post({ type: "message", payload: p }));
    on("done", (p) => this.post({ type: "done", payload: p }));
    on("error", (p) => this.post({ type: "error", payload: p }));
    on("context/compacted", (p) => this.post({ type: "context/compacted", payload: p }));
    on("subagent/start", (p) => this.post({ type: "subagent/start", payload: p }));
    on("subagent/text", (p) => this.post({ type: "subagent/text", payload: p }));
    on("subagent/thinking", (p) => this.post({ type: "subagent/thinking", payload: p }));
    on("subagent/tool_call", (p) => this.post({ type: "subagent/tool_call", payload: p }));
    on("subagent/tool_result", (p) => this.post({ type: "subagent/tool_result", payload: p }));
    on("subagent/done", (p) => this.post({ type: "subagent/done", payload: p }));
    on("subagent/error", (p) => this.post({ type: "subagent/error", payload: p }));
  }
  post(message) {
    void this.view?.webview.postMessage(message);
  }
  async handleInbound(msg) {
    try {
      switch (msg.type) {
        case "send":
          if (msg.message)
            await this.handleSend(msg.message);
          break;
        case "cancel":
          await this.client.cancel();
          break;
        case "command":
          if (msg.cmd)
            await this.client.runCommand(msg.cmd, msg.args ?? []);
          break;
        case "modelPick":
          await vscode7.commands.executeCommand("z3cli.model.pick");
          break;
        case "modePick":
          await vscode7.commands.executeCommand("z3cli.mode.pick");
          break;
        case "routePick":
          await vscode7.commands.executeCommand("z3cli.route.switch");
          break;
        case "ready": {
          const ready = this.client.getReady();
          if (ready)
            this.post({ type: "ready", payload: ready });
          break;
        }
      }
    } catch (err) {
      logError(`chat handleInbound ${msg.type}`, err);
      this.post({ type: "error", payload: { message: err.message } });
    }
  }
  async handleSend(rawMessage) {
    const message = rawMessage.trim();
    if (!message)
      return;
    if (message.startsWith("/")) {
      const [cmd, ...args] = splitArgs(message);
      if (cmd) {
        const result = await this.client.runCommand(cmd, args);
        this.postSystem(formatCommandResult(cmd, result));
      }
      return;
    }
    await this.client.chat(message, this.editorContextParams(message));
  }
  editorContextParams(message) {
    const editor = vscode7.window.activeTextEditor;
    if (!editor || editor.document.uri.scheme !== "file")
      return {};
    const shouldAttach = !editor.selection.isEmpty || /\b(this|current|active|selected|selection|file|buffer)\b/i.test(message);
    if (!shouldAttach)
      return {};
    return { attachments: [{ path: editor.document.uri.fsPath }] };
  }
  postSystem(content) {
    this.post({
      type: "message",
      payload: {
        id: `local-${Date.now()}`,
        role: "system",
        content,
        timestamp: Date.now()
      }
    });
  }
  dispose() {
    for (const s of this.subscriptions)
      s.dispose();
  }
};
function formatCommandResult(cmd, result) {
  if (result && typeof result === "object") {
    const payload = result;
    if (typeof payload.text === "string")
      return payload.text;
    if (typeof payload.message === "string")
      return payload.message;
    if (typeof payload.mode === "string")
      return `${cmd}: ${payload.mode}`;
    if (typeof payload.tools_enabled === "boolean")
      return `Tools enabled: ${payload.tools_enabled}`;
    if (typeof payload.tools_write === "boolean")
      return `Tool write access: ${payload.tools_write}`;
    if (typeof payload.verify_hooks === "boolean")
      return `Verification hooks: ${payload.verify_hooks}`;
    if (typeof payload.ok === "boolean")
      return `${cmd}: ok`;
    return `${cmd}: ${JSON.stringify(payload, null, 2)}`;
  }
  return `${cmd}: ${String(result ?? "ok")}`;
}

// src/fim/provider.ts
var vscode8 = __toESM(require("vscode"));

// src/fim/qwen_fim.ts
var QWEN_DEFAULT = {
  prefixTok: "<|fim_prefix|>",
  suffixTok: "<|fim_suffix|>",
  middleTok: "<|fim_middle|>",
  defaultStops: ["<|endoftext|>", "<|fim_pad|>", "<|file_separator|>", "<|repo_name|>"]
};
var QWEN_CODER = {
  ...QWEN_DEFAULT,
  defaultStops: ["<|endoftext|>", "<|fim_pad|>", "<|file_separator|>"]
};
var STARCODER = {
  prefixTok: "<fim_prefix>",
  suffixTok: "<fim_suffix>",
  middleTok: "<fim_middle>",
  defaultStops: ["<file_sep>", "<|endoftext|>"]
};
var TEMPLATES = {
  default: QWEN_DEFAULT,
  qwen: QWEN_DEFAULT,
  qwen3: QWEN_DEFAULT,
  qwen35: QWEN_DEFAULT,
  qwencoder: QWEN_CODER,
  starcoder: STARCODER
};
var MODEL_TEMPLATE_MAP = [
  [/navi|farore|nayru|qwen3?\.5/i, "qwen35"],
  [/qwen3?-coder|oracle-coder/i, "qwencoder"],
  [/oracle/i, "qwen"],
  [/starcoder|deepseek-coder/i, "starcoder"]
];
function pickTemplate(model) {
  for (const [re, key] of MODEL_TEMPLATE_MAP) {
    if (re.test(model))
      return TEMPLATES[key] ?? TEMPLATES.default;
  }
  return TEMPLATES.default;
}
function buildFimPrompt(prefix, suffix, model) {
  const tpl = pickTemplate(model);
  return `${tpl.prefixTok}${prefix}${tpl.suffixTok}${suffix}${tpl.middleTok}`;
}
function fimStopTokens(model, extra) {
  const tpl = pickTemplate(model);
  return Array.from(/* @__PURE__ */ new Set([...tpl.defaultStops, ...extra]));
}

// src/fim/hot_path.ts
var HotPathError = class extends Error {
  constructor(message, code) {
    super(message);
    this.code = code;
    this.name = "HotPathError";
  }
};
var DEFAULT_TIMEOUT_MS = 4e3;
async function postCompletion(apiBase, body, signal, timeoutMs) {
  const url = trimSlash(apiBase) + "/completions";
  const localController = new AbortController();
  let timedOut = false;
  const onCallerAbort = () => localController.abort();
  if (signal.aborted) {
    localController.abort();
  } else {
    signal.addEventListener("abort", onCallerAbort);
  }
  const tHandle = setTimeout(() => {
    timedOut = true;
    localController.abort();
  }, timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: localController.signal
    });
    if (!res.ok) {
      throw new HotPathError(`HTTP ${res.status} ${res.statusText}`, "http");
    }
    const json = await res.json();
    return json.choices?.[0]?.text ?? "";
  } catch (err) {
    if (err.name === "AbortError") {
      if (timedOut) {
        throw new HotPathError(`timeout after ${timeoutMs}ms`, "timeout");
      }
      throw new HotPathError("aborted", "abort");
    }
    if (err instanceof HotPathError)
      throw err;
    throw new HotPathError(`${err.message}`, "connect");
  } finally {
    clearTimeout(tHandle);
    signal.removeEventListener("abort", onCallerAbort);
  }
}
function trimSlash(s) {
  return s.endsWith("/") ? s.slice(0, -1) : s;
}
async function fimHotPath(req, resolved, signal) {
  const prompt = buildFimPrompt(req.prefix, req.suffix, req.model);
  const stop = fimStopTokens(req.model, req.stop);
  const body = {
    model: resolved.modelId,
    prompt,
    max_tokens: req.maxTokens,
    temperature: req.temperature,
    stop,
    stream: false
  };
  const text = await postCompletion(resolved.apiBase, body, signal, DEFAULT_TIMEOUT_MS);
  return { text, endpoint: resolved.backend };
}

// src/fim/cold_path.ts
var ColdPathAborted = class extends Error {
  constructor() {
    super("aborted");
    this.name = "ColdPathAborted";
  }
};
async function fimColdPath(client2, req, signal) {
  if (signal?.aborted)
    throw new ColdPathAborted();
  const params = {
    prefix: req.prefix,
    suffix: req.suffix,
    max_tokens: req.maxTokens,
    temperature: req.temperature,
    stop: req.stop
  };
  if (req.model)
    params.model = req.model;
  const requestPromise = client2.request("complete", params, 2e4);
  const racers = [requestPromise];
  let abortReject = null;
  let onAbort = null;
  if (signal) {
    racers.push(
      new Promise((_, reject) => {
        abortReject = reject;
        onAbort = () => {
          abortReject?.(new ColdPathAborted());
          abortReject = null;
        };
        signal.addEventListener("abort", onAbort);
      })
    );
  }
  try {
    const result = await Promise.race(racers) ?? {};
    return {
      text: result.text ?? "",
      finishReason: result.finish_reason,
      promptTokens: result.prompt_tokens,
      completionTokens: result.completion_tokens
    };
  } finally {
    if (signal && onAbort)
      signal.removeEventListener("abort", onAbort);
  }
}

// src/fim/provider.ts
var MAX_TRIM = 16;
var Z3cliInlineCompletionProvider = class {
  constructor(client2, readConfig2, resolver) {
    this.client = client2;
    this.readConfig = readConfig2;
    this.resolver = resolver;
  }
  debounceTimer = null;
  debounceCancel = null;
  currentController = null;
  async provideInlineCompletionItems(document, position, context, token) {
    const cfg = this.readConfig();
    if (!cfg.fim.enabled)
      return null;
    if (!cfg.fim.languages.includes(document.languageId))
      return null;
    this.cancelInFlight();
    const debounceMs = cfg.fim.debounceMs;
    let cancelled = false;
    await new Promise((resolve) => {
      this.debounceCancel = () => {
        cancelled = true;
        resolve();
      };
      this.debounceTimer = setTimeout(() => {
        this.debounceTimer = null;
        this.debounceCancel = null;
        resolve();
      }, debounceMs);
    });
    if (cancelled || token.isCancellationRequested)
      return null;
    const controller = new AbortController();
    this.currentController = controller;
    const onTokenCancel = token.onCancellationRequested(() => controller.abort());
    const req = buildRequest(document, position, cfg);
    if (req.prefix.trim().length === 0) {
      onTokenCancel.dispose();
      return null;
    }
    let text = "";
    const resolved = await this.resolver.resolve(req.model, false);
    if (controller.signal.aborted) {
      onTokenCancel.dispose();
      return null;
    }
    if (resolved && resolved.apiBase) {
      try {
        const hot = await fimHotPath(req, resolved, controller.signal);
        text = hot.text;
      } catch (err) {
        if (err instanceof HotPathError && err.code === "abort") {
          onTokenCancel.dispose();
          return null;
        }
        log(`hot_path failed: ${err.message}; trying cold_path`);
      }
    } else {
      log(`resolver miss for ${req.model}; falling through to cold_path`);
    }
    if (controller.signal.aborted) {
      onTokenCancel.dispose();
      return null;
    }
    if (!text) {
      try {
        const cold = await fimColdPath(this.client, req, controller.signal);
        text = cold.text;
      } catch (rpcErr) {
        if (rpcErr instanceof ColdPathAborted) {
          onTokenCancel.dispose();
          return null;
        }
        logError("cold_path", rpcErr);
        onTokenCancel.dispose();
        return null;
      }
    }
    onTokenCancel.dispose();
    text = trimSuggestion(text, req.suffix);
    if (!text)
      return null;
    const item = new vscode8.InlineCompletionItem(text, new vscode8.Range(position, position));
    return [item];
  }
  cancelInFlight() {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    if (this.debounceCancel) {
      const cancel = this.debounceCancel;
      this.debounceCancel = null;
      cancel();
    }
    if (this.currentController) {
      this.currentController.abort();
      this.currentController = null;
    }
  }
};
function buildRequest(doc, pos, cfg) {
  const offset = doc.offsetAt(pos);
  const text = doc.getText();
  const prefixStart = Math.max(0, offset - cfg.fim.contextPrefixChars);
  const suffixEnd = Math.min(text.length, offset + cfg.fim.contextSuffixChars);
  return {
    prefix: text.slice(prefixStart, offset),
    suffix: text.slice(offset, suffixEnd),
    model: cfg.fim.model,
    maxTokens: cfg.fim.maxTokens,
    temperature: cfg.fim.temperature,
    stop: cfg.fim.stopTokens
  };
}
function trimSuggestion(suggestion, suffix) {
  if (!suggestion)
    return "";
  if (suffix) {
    const head = suffix.slice(0, MAX_TRIM);
    const idx = suggestion.indexOf(head);
    if (idx > 0 && head.length >= 4) {
      return suggestion.slice(0, idx);
    }
  }
  return suggestion;
}

// src/fim/resolver.ts
var ModelResolver = class {
  constructor(client2) {
    this.client = client2;
    client2.on("ready", () => this.cache.clear());
    client2.on("route/select", () => this.cache.clear());
    client2.on("event", (evt) => {
      const m = evt?.method;
      if (m === "context/compacted" || m === "ready")
        return;
      if (typeof m === "string" && m.startsWith("route/"))
        this.cache.clear();
    });
  }
  cache = /* @__PURE__ */ new Map();
  async resolve(alias, autoLoad = false) {
    const key = alias.trim().toLowerCase();
    if (!key)
      return null;
    if (!autoLoad) {
      const cached = this.cache.get(key);
      if (cached)
        return cached;
    }
    try {
      const raw = await this.client.request(
        "inventory/resolve",
        { alias, autoLoad },
        5e3
      );
      const resolved = {
        alias: stringField(raw.alias, alias),
        canonicalName: stringField(raw.canonical_name, alias),
        modelId: stringField(raw.model_id, alias),
        backend: stringField(raw.backend, "studio"),
        apiBase: stringField(raw.api_base, "")
      };
      if (!resolved.apiBase) {
        log(`inventory/resolve returned empty api_base for ${alias}`);
        return null;
      }
      this.cache.set(key, resolved);
      return resolved;
    } catch (err) {
      log(`inventory/resolve failed for ${alias}: ${err.message}`);
      return null;
    }
  }
  clear() {
    this.cache.clear();
  }
};
function stringField(value, fallback) {
  return typeof value === "string" && value ? value : fallback;
}

// src/extension.ts
var client = null;
var statusBar = null;
var chatPanel = null;
function activate(context) {
  output().show(true);
  const version = String(context.extension.packageJSON.version ?? "unknown");
  log(`activate ${context.extension.id}@${version}`);
  const cfg = readConfig();
  client = new Z3cliClient({ cfg });
  statusBar = new StatusBar(client);
  context.subscriptions.push(statusBar);
  client.on("error", (params) => {
    log(`backend error: ${params.message}`);
  });
  client.once("ready", (ready) => {
    log(`ready \xB7 backend=${ready.backend} model=${ready.active_model} workspace=${ready.workspace}`);
    void applyDefaultRoute(client, cfg);
  });
  client.on("event", (evt) => {
  });
  client.start();
  const routes = new RoutesTreeProvider(client);
  const commands3 = new CommandsTreeProvider();
  context.subscriptions.push(
    vscode9.window.registerTreeDataProvider("z3cli.routes", routes),
    vscode9.window.registerTreeDataProvider("z3cli.commands", commands3)
  );
  registerCommands(context, client, { routes, commands: commands3 });
  chatPanel = new ChatPanelProvider(context, client);
  context.subscriptions.push(
    vscode9.window.registerWebviewViewProvider("z3cli.chat", chatPanel, {
      webviewOptions: { retainContextWhenHidden: true }
    })
  );
  const resolver = new ModelResolver(client);
  if (cfg.fim.enabled) {
    const provider = new Z3cliInlineCompletionProvider(client, () => readConfig(), resolver);
    const selector = cfg.fim.languages.map((language) => ({
      scheme: "file",
      language
    }));
    context.subscriptions.push(
      vscode9.languages.registerInlineCompletionItemProvider(selector, provider)
    );
  }
  context.subscriptions.push(
    vscode9.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("z3cli")) {
        log("configuration changed; restart Z3CLI to apply transport changes");
      }
    })
  );
}
function deactivate() {
  log("deactivate");
  void client?.stop();
  client = null;
  statusBar = null;
  chatPanel = null;
}
async function applyDefaultRoute(c, cfg) {
  const route = cfg.chat.defaultRoute.trim();
  if (!route)
    return;
  try {
    await c.request("route/select", { route });
    log(`applied default route ${route}`);
  } catch (err) {
    logError("default route", err);
  }
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  activate,
  deactivate
});
//# sourceMappingURL=extension.js.map
