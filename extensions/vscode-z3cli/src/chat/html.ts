export const CHAT_HTML = /* html */ `<!doctype html>
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
    <button id="modelBtn" title="Switch model">model: …</button>
    <button id="modeBtn" title="Switch mode">mode: …</button>
    <button id="routeBtn" title="Switch route">route: …</button>
    <span id="status"></span>
  </header>
  <div id="transcript"></div>
  <footer>
    <textarea id="input" placeholder="Talk to Oracle…  Use @file, #room:0x45, !shell, /slash"></textarea>
    <div class="row">
      <span class="hint grow">Enter to send · Shift+Enter newline · Esc cancel</span>
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
      body.append(el("div", null, p.reason ? title + " · " + p.reason : title));
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
        const diff = el("pre", "review-diff", p.diff_lines.join("\\n") + (p.omitted ? "\\n… " + p.omitted + " more lines" : ""));
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
        ? " · cache " + p.cache_read_tokens + "/" + ((p.cache_read_tokens + (p.cache_creation_tokens || 0))) : "";
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
        "compacted " + p.replaced + " turns · " + p.tokens_before + " → " + p.tokens_after + " tokens");
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
          "tokens " + (p.prompt_tokens + p.completion_tokens) + (p.error ? " · error: " + p.error : ""));
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
      modelBtn.textContent = "model: " + (p.active_model || "—");
      modeBtn.textContent = "mode: " + (p.mode || "—");
      const route = p.studio_node || p.llamacpp_node || p.backend || "—";
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
</html>`;
