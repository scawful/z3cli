#!/usr/bin/env bash
# Install the packaged .vsix into VSCode and any installed forks.
#
# Usage: ./scripts/install-vsix.sh [--dry-run]
set -euo pipefail

cd "$(dirname "$0")/.."

EXTENSION_ID="scawful.vscode-z3cli"
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
if [[ $# -gt 0 ]]; then
  echo "usage: ./scripts/install-vsix.sh [--dry-run]" >&2
  exit 2
fi

VSIX="$(ls -1t vscode-z3cli*.vsix 2>/dev/null | head -1 || true)"
if [[ -z "$VSIX" ]]; then
  echo "no .vsix found; run scripts/package-vsix.sh first" >&2
  exit 1
fi
VSIX_VERSION="$(
  unzip -p "$VSIX" extension/package.json \
    | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>process.stdout.write(JSON.parse(s).version))"
)"

echo "==> installing $VSIX ($EXTENSION_ID@$VSIX_VERSION)"
FAILURES=0

run_install() {
  local label="$1"
  local path="$2"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  - $label ($path) uninstall/install [dry-run]"
    return
  fi
  echo "  - $label ($path)"
  "$path" --uninstall-extension "$EXTENSION_ID" >/dev/null 2>&1 || true
  "$path" --install-extension "$VSIX" --force
  local installed
  installed="$("$path" --list-extensions --show-versions | grep -i "^${EXTENSION_ID}@${VSIX_VERSION}$" || true)"
  if [[ -z "$installed" ]]; then
    echo "    ! $label did not report ${EXTENSION_ID}@${VSIX_VERSION} after install" >&2
    echo "      Check whether the editor is still running the old extension host, then quit/reopen and rerun." >&2
    return 1
  fi
  echo "    installed $installed"
}

install_with() {
  local label="$1"
  shift
  local candidate resolved
  for candidate in "$@"; do
    if [[ "$candidate" == */* ]]; then
      if [[ -x "$candidate" ]]; then
        if ! run_install "$label" "$candidate"; then
          FAILURES=$((FAILURES + 1))
        fi
        return
      fi
      continue
    fi
    if resolved="$(command -v "$candidate" 2>/dev/null)"; then
      if ! run_install "$label" "$resolved"; then
        FAILURES=$((FAILURES + 1))
      fi
      return
    fi
  done
  echo "  - $label not found"
}

install_with "VS Code" \
  code \
  "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" \
  "$HOME/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
install_with "VS Code Insiders" \
  code-insiders \
  "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code-insiders" \
  "$HOME/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code-insiders"
install_with "Cursor" \
  cursor \
  "/Applications/Cursor.app/Contents/Resources/app/bin/cursor" \
  "$HOME/Applications/Cursor.app/Contents/Resources/app/bin/cursor"
install_with "Antigravity" \
  antigravity \
  "/Applications/Antigravity.app/Contents/Resources/app/bin/antigravity" \
  "$HOME/Applications/Antigravity.app/Contents/Resources/app/bin/antigravity" \
  "$HOME/Applications/Antigravity GPU.app/Contents/Resources/app/bin/antigravity"
install_with "Windsurf" \
  windsurf \
  "/Applications/Windsurf.app/Contents/Resources/app/bin/windsurf" \
  "$HOME/Applications/Windsurf.app/Contents/Resources/app/bin/windsurf"

if [[ "$FAILURES" -gt 0 ]]; then
  echo "==> done with $FAILURES failed install target(s)" >&2
  exit 1
fi

echo "==> done"
