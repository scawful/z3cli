#!/usr/bin/env bash
# Regenerate AppIcon PNGs from AppIcon-1024.png in the bundled asset catalog.
set -euo pipefail
ICONSET="$(cd "$(dirname "$0")/.." && pwd)/ios/ZeldaRemoteAppIcon/Assets.xcassets/AppIcon.appiconset"
MASTER="$ICONSET/AppIcon-1024.png"
cd "$ICONSET"
[[ -f "$MASTER" ]] || { echo "Missing $MASTER"; exit 1; }
for px in 20 29 40 58 60 76 80 87 120 152 167 180; do
  sips -z "$px" "$px" "$MASTER" --out "AppIcon-${px}.png" >/dev/null
done
echo "Regenerated AppIcon PNGs in $ICONSET"
