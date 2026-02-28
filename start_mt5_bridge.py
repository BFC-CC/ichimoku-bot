"""
start_mt5_bridge.py
────────────────────────────────────────────────────────────────────────────
Starts the mt5linux socket bridge that lets the Linux Python process
communicate with MetaTrader5 running inside Wine.

Keep this script running in a separate terminal while using the dashboard.

Usage
-----
    python3 start_mt5_bridge.py

Requirements
------------
    - Wine installed and configured (run setup_mt5_wine.sh first)
    - MT5 terminal running and logged in inside Wine
    - mt5linux installed: pip install mt5linux
"""

import subprocess
import sys
from pathlib import Path

WINE_PREFIX  = Path.home() / ".mt5wine"
WIN_PYTHON   = WINE_PREFIX / "drive_c" / "Python310" / "python.exe"
HOST         = "localhost"
PORT         = 18812


def main():
    print(f"Starting mt5linux bridge on {HOST}:{PORT} ...")
    print(f"Wine prefix : {WINE_PREFIX}")
    print(f"Win Python  : {WIN_PYTHON}")
    print("Press Ctrl+C to stop.\n")

    bridge_code = (
        f"import sys; sys.path.insert(0, '.'); "
        f"from mt5linux import ServerSocket; "
        f"ServerSocket('{HOST}', {PORT}).start()"
    )

    env = {"WINEPREFIX": str(WINE_PREFIX)}

    import os
    env.update(os.environ)
    env["WINEPREFIX"] = str(WINE_PREFIX)

    try:
        subprocess.run(
            ["wine", str(WIN_PYTHON), "-c", bridge_code],
            env=env,
            check=True,
        )
    except KeyboardInterrupt:
        print("\nBridge stopped.")
    except FileNotFoundError:
        print("ERROR: wine not found. Run setup_mt5_wine.sh first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
