# vscode-z3cli Handoff

Date: 2026-04-26

## Current State

`vscode-z3cli` is a VSCode/Cursor/Antigravity extension that talks to
`z3cli --serve` over NDJSON JSON-RPC. It provides:

- Sidebar chat webview with streamed text/thinking/tool/subagent events.
- Routes and commands TreeViews in the Z3CLI activity-bar container.
- Command palette entries for route/model/mode/workspace/ROM/FIM controls.
- Inline FIM autocomplete with a direct local `/v1/completions` hot path.
- Cold-path FIM fallback through the backend `complete` JSON-RPC method.

The extension package was bumped to `0.1.1` after discovering that Cursor and
Antigravity were still running the stale `0.1.0` bundle.

## Important Files

- `src/extension.ts` wires activation, client, views, chat, routes, commands,
  and FIM provider.
- `src/ipc/client.ts` owns the child process, JSON-RPC transport, restart
  behavior, ready handling, and local checkout detection.
- `src/fim/provider.ts` owns debounce, cancellation, hot/cold path selection,
  and inline completion item creation.
- `src/fim/hot_path.ts` posts FIM prompts directly to a resolved OpenAI-style
  `/completions` endpoint.
- `src/fim/cold_path.ts` calls backend `complete` and is UI-cancellation-aware.
- `src/fim/resolver.ts` calls `inventory/resolve` and caches alias to runtime
  model id plus API base.
- `src/commands/register.ts` owns command palette actions and direct
  `route/*` calls.
- `scripts/install-vsix.sh` installs the packaged VSIX into VSCode, Cursor,
  Antigravity, and Windsurf when present.
- Backend RPCs live in `src/app/serve.py`, with request/response typing in
  `src/app/ipc_schema.py`.

## Backend Additions

Implemented backend support:

- `complete` JSON-RPC method for single-shot completions used by FIM cold path.
- `route/list`, `route/select`, `route/status`, and `route/probe`.
- `inventory/query`, `inventory/snapshot`, `inventory/refresh`, and
  `inventory/resolve`.

`inventory/resolve` maps a logical alias such as `navi` to:

- canonical model name
- runtime model id
- backend name
- API base

It defaults `autoLoad=false` so FIM hot-path resolution can ask "is this loaded?"
without triggering a load. The potentially blocking model resolution work is
run through `asyncio.to_thread()`.

## Latest Install State

Updated 2026-04-25 21:54 EDT.

The stale-install issue was repaired locally. VS Code, Cursor, and Antigravity
now report:

```text
scawful.vscode-z3cli@0.1.1
```

The stale `scawful.vscode-z3cli-0.1.0` extension directories were removed from
the VS Code, Cursor, and Antigravity extension stores. The rebuilt installed
bundle now logs its installed extension id/version at activation, so the Z3CLI
output channel should start with a line shaped like:

```text
activate scawful.vscode-z3cli@0.1.1
```

Fully quit and reopen the editor before testing; a window reload can still keep
an old extension host alive.

## Previous Active Issue

Cursor and Antigravity logs still showed stale `0.1.0` behavior:

```text
spawn: python3 -m z3cli --serve --workspace /Users/scawful/src/hobby/yaze
stderr: ... No module named z3cli
restart in ...
```

That log is not from the fixed bundle. The fixed `0.1.1` bundle should log:

```text
using z3cli checkout /Users/scawful/src/hobby/z3cli
spawn: python3 -m z3cli --serve --workspace ... (cwd /Users/scawful/src/hobby/z3cli)
```

The issue is installation/cache, not the source fix. The local VSIX contains
`scawful.vscode-z3cli@0.1.1`, but the editors were still reporting
`scawful.vscode-z3cli@0.1.0`.

## Install / Repair Commands

From the extension directory:

```bash
cd /Users/scawful/src/hobby/z3cli/extensions/vscode-z3cli
scripts/install-vsix.sh
```

The installer now:

- Reads the VSIX version from `extension/package.json`.
- Uninstalls `scawful.vscode-z3cli`.
- Installs the local VSIX.
- Verifies each editor reports the expected installed version.
- Tries all detected editors before exiting nonzero on failures.

Expected successful line:

```text
installed scawful.vscode-z3cli@0.1.1
```

Manual Cursor repair if the installer does not replace the stale bundle:

```bash
cd /Users/scawful/src/hobby/z3cli/extensions/vscode-z3cli
'/Applications/Cursor.app/Contents/Resources/app/bin/cursor' --uninstall-extension scawful.vscode-z3cli
rm -rf ~/.cursor/extensions/scawful.vscode-z3cli-0.1.0
'/Applications/Cursor.app/Contents/Resources/app/bin/cursor' --install-extension vscode-z3cli.vsix --force
'/Applications/Cursor.app/Contents/Resources/app/bin/cursor' --list-extensions --show-versions | grep z3cli
```

Manual Antigravity repair is the same shape:

```bash
cd /Users/scawful/src/hobby/z3cli/extensions/vscode-z3cli
antigravity --uninstall-extension scawful.vscode-z3cli
rm -rf ~/.antigravity/extensions/scawful.vscode-z3cli-0.1.0
antigravity --install-extension vscode-z3cli.vsix --force
antigravity --list-extensions --show-versions | grep z3cli
```

Fully quit and reopen the editor after install. Window reload may not be enough
if the extension host cached `0.1.0`.

## Build / Package Commands

```bash
cd /Users/scawful/src/hobby/z3cli/extensions/vscode-z3cli
npm run typecheck
npm run build
npx vsce package --allow-missing-repository --out vscode-z3cli.vsix
```

Protocol generation after IPC schema changes:

```bash
cd /Users/scawful/src/hobby/z3cli
python3 scripts/generate_protocol_ts.py
```

That updates both frontend and extension protocol types and copies the command
catalog.

## Validation Already Run

Focused backend tests:

```bash
python3 -m pytest tests/test_inventory_resolve.py tests/test_serve_complete.py tests/test_provider_completion.py -q
```

Latest observed result:

```text
18 passed, 1 warning
```

Extension checks:

```bash
npm run typecheck
npm run build
npx vsce package --allow-missing-repository --out vscode-z3cli.vsix
```

Latest observed result:

- TypeScript clean.
- Production esbuild clean.
- VSIX packaged as `vscode-z3cli.vsix`.
- VSIX package metadata reports `scawful.vscode-z3cli@0.1.1`.

Manual `python3 -m z3cli --serve ...` from the checkout gets past module import
in the sandbox, but then fails here on session-file writes under
`~/.local/share/z3cli` because Codex cannot write there. That is a sandbox
artifact, not expected in a normal editor session.

## Live Smoke Checklist

After the editor reports `scawful.vscode-z3cli@0.1.1`:

1. Open `/Users/scawful/src/hobby/yaze` or another normal workspace.
2. Open the Z3CLI output channel.
3. Confirm startup logs include `using z3cli checkout ...` and `(cwd .../z3cli)`.
4. Open the Z3CLI activity-bar container and verify Chat, Routes, Commands views.
5. Run `Z3CLI: Switch Route`; output should use `route/list` and `route/select`,
   not `/route` slash dispatch.
6. Send a small chat message and verify streamed response events.
7. Open a source file and pause mid-line to trigger FIM.
8. Type quickly while FIM is pending; prior request should cancel without log spam.
9. Unload local models and trigger FIM; resolver should miss and cold path should
   auto-load or return a clean backend error.

## Known Follow-Ups

- Add a small TS test harness, likely Vitest plus a minimal `vscode` mock, for
  `splitArgs`, FIM timeout/cancellation, resolver behavior, and IPC restarts.
- Cold-path cancellation is UI-local. The extension stops awaiting the RPC, but
  the backend `complete` request can still finish. Add request-id cancellation if
  backend churn becomes visible while typing fast.
- Tighten the webview CSP by moving from inline script/style to nonce-based
  script execution.
- Clarify `z3cli.serveCommand` semantics. It currently acts like an executable
  override with generated `--serve` args appended, not a truly complete command
  override.

## Debug Notes

If logs show `No module named z3cli` and no `(cwd ...)` suffix, the editor is
still running `0.1.0` or another stale bundle.

If logs show `(cwd /Users/scawful/src/hobby/z3cli)` but backend startup fails,
then investigate the backend error directly. The import problem is fixed in that
case.

If the installer says it installed `0.1.1` but the editor still loads `0.1.0`,
fully quit the editor, remove the stale extension directory, reinstall, then
check `--list-extensions --show-versions`.
