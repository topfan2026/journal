"""Give the website's fundamentals connector its Financial Modeling Prep key (Scanner site tab > "Add FMP key").

The Stock Analyzer needs company figures (P/E, margins, returns). The fundamentals connector gets them from a
free Financial Modeling Prep key kept in its own .env file. This asks you for the key in a small box (it is
never shown in the log), writes it into that .env, and restarts the connector.

    python fundamentals_key.py [key]
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

KEY_NAME = "FMP_API_KEY"
PATH_RE = re.compile(r'[A-Za-z]:\\[^"\r\n]*?\bapp\.py', re.IGNORECASE)
PORT_DEFAULT = 8766


def set_env_value(text: str, name: str, value: str) -> str:
    """The .env text with `name=value` set: the existing line is replaced, or the line is added at the end."""
    line = f"{name}={value}"
    pattern = re.compile(rf"^[ \t]*{re.escape(name)}[ \t]*=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    return text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"


def looks_like_key(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{16,80}", key.strip()))


def _powershell(command: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
    return (out.stdout or "").strip()


def find_connector() -> tuple[Path, str] | None:
    """(app.py, the command line it runs with) of the running fundamentals connector."""
    text = _powershell("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'fundamentals_conn[e]ctor' } "
                       "| ForEach-Object { $_.CommandLine }")
    for line in text.splitlines():
        m = PATH_RE.search(line)
        if m:
            return Path(m.group(0)), line.strip()
    return None


def stop_connector() -> None:
    _powershell("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'fundamentals_conn[e]ctor' } "
                "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")


def _port_from(env_file: Path) -> int:
    try:
        m = re.search(r"^[ \t]*PORT[ \t]*=[ \t]*(\d+)", env_file.read_text(encoding="utf-8"), re.MULTILINE)
        return int(m.group(1)) if m else PORT_DEFAULT
    except OSError:
        return PORT_DEFAULT


def _port_open(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def ask_for_key() -> str:
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    key = simpledialog.askstring("Financial Modeling Prep key", "Paste your free key from financialmodelingprep.com:", show="*", parent=root) or ""
    root.destroy()
    return key.strip()


def main(argv: list[str]) -> int:
    found = find_connector()
    if found is None:
        print("I couldn't find the fundamentals connector running. Start it first (it is the program that serves the "
              "Investment Planner's company figures), then click this again.")
        return 1
    app, command = found
    env_file = app.with_name(".env")
    print("fundamentals connector folder:", app.parent)
    key = argv[0].strip() if argv else ask_for_key()
    if not key:
        print("No key entered - nothing changed.")
        return 1
    if not looks_like_key(key):
        print("That doesn't look like a Financial Modeling Prep key (letters and numbers, 16+ characters). Nothing changed.")
        return 1
    old = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if old:
        env_file.with_name(".env.old").write_text(old, encoding="utf-8")
    env_file.write_text(set_env_value(old, KEY_NAME, key), encoding="utf-8")
    print(f"saved the key into {env_file.name} (the old file is kept as .env.old); restarting the connector...")
    stop_connector()
    time.sleep(2)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(command, cwd=str(app.parent), shell=True, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = _port_from(env_file)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if _port_open(port):
            print("DONE: the fundamentals connector is back with your key. In Stock Analyzer, run a ticker again (e.g. AAPL).")
            return 0
        time.sleep(2)
    print("The connector didn't come back within 45 seconds. Start it the way you normally do; the key is already saved.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
