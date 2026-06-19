#!/usr/bin/env bash
# SmartGen Linux/macOS setup script
# Usage: bash setup.sh
# Creates .venv, installs deps, copies .env.example → .env

set -euo pipefail

echo ""
echo " SmartGen setup (Linux/macOS)"
echo " ============================"
echo ""

# ── Python version check ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.10+ from https://python.org"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "[ERROR] Python 3.10+ required. Found: $PY_VER"
    exit 1
fi
echo "[OK] Python $PY_VER"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV=".venv"
if [ ! -d "$VENV" ]; then
    echo "[setup] Creating virtual environment..."
    python3 -m venv "$VENV"
else
    echo "[OK] Virtual environment already exists"
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ── PyTorch (CPU by default) ──────────────────────────────────────────────────
echo "[setup] Installing PyTorch (CPU)..."
echo "        For CUDA: pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121"
"$PIP" install --quiet torch==2.3.1 || { echo "[ERROR] PyTorch install failed"; exit 1; }

# ── Project dependencies ──────────────────────────────────────────────────────
echo "[setup] Installing project dependencies..."
"$PIP" install --quiet -r requirements.txt

# ── Environment file ──────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp ".env.example" ".env"
        echo "[setup] Created .env from .env.example"
    fi
else
    echo "[OK] .env already exists"
fi

echo ""
echo " Setup complete!"
echo " ─────────────────────────────────────────────────"
echo " Start server:  $PY -m uvicorn server.main:app --host 0.0.0.0 --port 8000"
echo ""
