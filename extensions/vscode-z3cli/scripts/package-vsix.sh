#!/usr/bin/env bash
# Bundle the extension and produce a .vsix for VSCode/Cursor/Antigravity.
#
# Usage: ./scripts/package-vsix.sh
#
# Output: vscode-z3cli-<version>.vsix in the extension root.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d node_modules ]]; then
  echo "==> npm install"
  npm install
fi

echo "==> esbuild"
node esbuild.config.mjs --production

echo "==> vsce package"
BASE_URL="https://github.com/scawful/z3cli/raw/master/extensions/vscode-z3cli"
npx --yes @vscode/vsce package --out vscode-z3cli.vsix --baseContentUrl "$BASE_URL"

echo "==> done: $(pwd)/vscode-z3cli.vsix"
