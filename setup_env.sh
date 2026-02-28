#!/usr/bin/env bash
# setup_env.sh — install all tools required by the Ichimoku bot
# Run once: bash setup_env.sh
set -e

echo "==> Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y git python3-pip

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Done. You can now run:"
echo "    python run_backtest.py"
echo "    python bot.py"
echo "    pytest tests/ -v"
