#!/usr/bin/env bash
# Builds dist/PixSift.app. Run from anywhere: packaging/build_mac.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"

npm --prefix "$ROOT/frontend" ci
npm --prefix "$ROOT/frontend" run build
"$PY" -m pip install -q -e "$ROOT/backend[desktop,build]"
"$PY" "$ROOT/packaging/make_icon.py"
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" --workpath "$ROOT/build" "$ROOT/packaging/pixsift.spec"
echo "Built $ROOT/dist/PixSift.app"
