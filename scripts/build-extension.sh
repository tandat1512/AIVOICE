#!/usr/bin/env bash
# Build SmartGen Chrome extension zip for distribution (sideload)
# Output: dist/smartgen-extension.zip

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
OUT="$DIST/smartgen-extension.zip"
SRC="$ROOT/extension"

if [ ! -d "$SRC" ]; then
    echo "[ERROR] extension/ directory not found at $SRC"
    exit 1
fi

mkdir -p "$DIST"
rm -f "$OUT"

echo "[build] Zipping extension..."

# Exclude .DS_Store, Thumbs.db, *.log from the zip
(cd "$SRC" && zip -r "$OUT" . \
    --exclude "*.DS_Store" \
    --exclude "Thumbs.db" \
    --exclude "*.log")

echo "[OK] Extension zipped to: $OUT"
