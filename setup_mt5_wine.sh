#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  MT5 on Ubuntu via Wine — automated setup script
#  Run once as your normal user (not root).
# ─────────────────────────────────────────────────────────────────────────────

set -e

WINE_PREFIX="$HOME/.mt5wine"
WIN_PYTHON_URL="https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
MT5_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
WIN_PYTHON="$WINE_PREFIX/drive_c/Python310/python.exe"

echo "======================================================="
echo "  MT5 Wine Setup for Ubuntu"
echo "======================================================="

# ── 1. Install Wine ───────────────────────────────────────────────────────────
echo ""
echo "[1/6] Installing Wine..."
sudo apt update -qq
sudo apt install -y wine wine64 winetricks wget

# ── 2. Create isolated Wine prefix ────────────────────────────────────────────
echo ""
echo "[2/6] Creating Wine prefix at $WINE_PREFIX..."
export WINEPREFIX="$WINE_PREFIX"
export WINEARCH=win64
wineboot --init 2>/dev/null || true

# ── 3. Install Windows Python 3.10 ───────────────────────────────────────────
echo ""
echo "[3/6] Downloading Windows Python 3.10..."
wget -q --show-progress "$WIN_PYTHON_URL" -O /tmp/python310_win.exe

echo "Installing Python 3.10 in Wine (silent)..."
WINEPREFIX="$WINE_PREFIX" wine /tmp/python310_win.exe \
    /quiet \
    InstallAllUsers=0 \
    PrependPath=1 \
    TargetDir="C:\\Python310"

# ── 4. Install MetaTrader5 Python package ────────────────────────────────────
echo ""
echo "[4/6] Installing MetaTrader5 package in Wine Python..."
WINEPREFIX="$WINE_PREFIX" wine "$WIN_PYTHON" -m pip install --upgrade pip MetaTrader5

# ── 5. Download MT5 terminal installer ───────────────────────────────────────
echo ""
echo "[5/6] Downloading MT5 terminal..."
wget -q --show-progress "$MT5_URL" -O /tmp/mt5setup.exe

echo ""
echo "[6/6] Launching MT5 installer..."
echo "  → Log in to your broker account when MT5 opens."
echo "  → After login, KEEP MT5 running in the background."
WINEPREFIX="$WINE_PREFIX" wine /tmp/mt5setup.exe

# ── 6. Install mt5linux in Linux venv ────────────────────────────────────────
echo ""
echo "Installing mt5linux in project venv..."
VENV="$(dirname "$0")/venv"
if [ -f "$VENV/bin/pip" ]; then
    "$VENV/bin/pip" install mt5linux
else
    pip install mt5linux
fi

# ── Done ──────────────────────────────────────────────────────────────────────
cat <<EOF

=======================================================
  Setup complete!
=======================================================

To use MT5 in the dashboard:

  1. Start the mt5linux bridge (keep this running):
       python3 -c "from mt5linux import MetaTrader5; MetaTrader5(host='localhost', port=18812)"

  Or use the helper script:
       python3 start_mt5_bridge.py

  2. Make sure MT5 terminal is running and logged in.

  3. Open the dashboard:
       python3 -m streamlit run app.py

The Live page will show "Connected · MetaTrader5 (wine)"
when the bridge is active.
EOF
