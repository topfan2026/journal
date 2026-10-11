"""Desktop-shortcut target: open TWS / IB Gateway so you can log in, then start the app
(app.py), which shows the bot and your account live.

Your IBKR username/password are typed into TWS's own login window; nothing is stored here.
Set TWS_PATH in .env if TWS isn't found automatically (e.g. C:\\Jts\\tws.exe).
"""
from __future__ import annotations

import glob
import os
import socket
import subprocess
import sys
from pathlib import Path

from src.common import env_int, env_str


def find_tws() -> str | None:
    explicit = env_str("TWS_PATH")
    if explicit and Path(explicit).exists():
        return explicit
    patterns = {
        "win32": [r"C:\Jts\tws.exe", r"C:\Jts\*\tws.exe", r"C:\Jts\ibgateway\*\ibgateway.exe"],
        "darwin": ["/Applications/Trader Workstation*.app", os.path.expanduser("~/Applications/Trader Workstation*.app"),
                   "/Applications/IB Gateway*.app", os.path.expanduser("~/Applications/IB Gateway*.app")],
    }.get(sys.platform, [os.path.expanduser("~/Jts/tws"), os.path.expanduser("~/Jts/*/tws"),
                         os.path.expanduser("~/Jts/ibgateway/*/ibgateway")])
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)  # newest version folder first
        if hits:
            return hits[0]
    return None


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def main() -> int:
    host, port = env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497)
    if not port_open(host, port):
        app = find_tws()
        if app:
            print(f"Opening {app}\n>>> Log in to your PAPER account in the IBKR window.")
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", app])
            else:
                subprocess.Popen([app], cwd=str(Path(app).parent))
        else:
            print("Couldn't find TWS / IB Gateway: start it yourself, or set TWS_PATH=... in .env.")
    import app as bot_app  # opens the app in your browser; shows "waiting for TWS" until you log in
    return bot_app.main()


if __name__ == "__main__":
    sys.exit(main())
