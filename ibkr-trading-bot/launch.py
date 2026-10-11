"""Desktop-shortcut target: open TWS / IB Gateway so you can log in, wait for the API port,
confirm the bot can connect, then open the dashboard.

Your IBKR username/password are typed into TWS's own login window; nothing is stored here.
Set TWS_PATH in .env if TWS isn't found automatically (e.g. C:\\Jts\\tws.exe).
"""
from __future__ import annotations

import glob
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from src.common import DASHBOARD_DIR, PROJECT_DIR, env_int, env_str

WAIT_SECONDS = 300


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
    print(f"IBKR bot launcher — API {host}:{port} ({'paper' if port in (7497, 4002) else 'LIVE'})\n")

    if port_open(host, port):
        print("TWS / IB Gateway is already running and logged in.")
    else:
        app = find_tws()
        if not app:
            print("Couldn't find TWS or IB Gateway. Start it yourself, or set TWS_PATH=... in .env.")
        else:
            print(f"Opening {app}\n>>> Log in to your PAPER account in the window that appears.")
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", app])
            else:
                subprocess.Popen([app], cwd=str(Path(app).parent))
        print(f"Waiting up to {WAIT_SECONDS // 60} min for the API port to open", end="", flush=True)
        deadline = time.monotonic() + WAIT_SECONDS
        while not port_open(host, port):
            if time.monotonic() > deadline:
                print("\nTimed out. Check File > Global Configuration > API > Settings (port, socket clients enabled).")
                input("Press Enter to close...")
                return 1
            print(".", end="", flush=True)
            time.sleep(3)
        print(" open.")
        time.sleep(3)  # TWS accepts the socket a moment before it accepts API clients

    print("\nTesting the API connection:")
    r = subprocess.run([sys.executable, str(PROJECT_DIR / "test_connect.py")], cwd=PROJECT_DIR)
    if r.returncode != 0:
        print("Connection test failed. If TWS shows an 'accept incoming connection' prompt, click Accept and retry.")

    dash = DASHBOARD_DIR / "index.html"
    if not dash.exists():
        subprocess.run([sys.executable, str(PROJECT_DIR / "compute_perf.py")], cwd=PROJECT_DIR, capture_output=True)
    if dash.exists():
        webbrowser.open(dash.as_uri())
        print(f"Opened dashboard: {dash}")

    input("\nAll set. The scheduled tasks run the bot. Press Enter to close this window...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
