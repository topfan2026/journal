"""Install a new IBKR connector app.py in one click (Scanner site tab > "Update connector (order flow)").

The connector is TradeLedger's small local program that gives the website its IBKR data. It lives in its own
folder (the one the "TradeLedger IBKR Connector" Windows task starts), so this finds that folder, saves the old
app.py next to it as app.py.old, copies in the new one you downloaded from GitHub (topfan2026/tradeledger >
services > ibkr_connector > app.py > Download raw file), restarts the connector and checks it knows order flow.

    python connector_update.py [path\\to\\downloaded\\app.py]

The new file is only taken from your Downloads folder (or the path you give), and only if it really is the
connector. Nothing is downloaded from the internet and nothing is published.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TASK = "TradeLedger IBKR Connector"
MARKER = b"/market-data/order-flow"  # only the new connector has this route
PATH_RE = re.compile(r'[A-Za-z]:\\[^"\r\n]*?\bapp\.py', re.IGNORECASE)


def app_path_from(text: str) -> Path | None:
    """The connector's app.py out of a task's arguments / a start command."""
    m = PATH_RE.search(text or "")
    return Path(m.group(0)) if m else None


def is_new_connector(path: Path) -> bool:
    try:
        return path.is_file() and MARKER in path.read_bytes()
    except OSError:
        return False


def pick_download(folder: Path, explicit: str | None = None) -> Path | None:
    """The newest app.py / "app (1).py" in Downloads that is the new connector."""
    if explicit:
        p = Path(explicit)
        return p if is_new_connector(p) else None
    found = [p for p in folder.glob("app*.py") if re.fullmatch(r"app( \(\d+\))?\.py", p.name) and is_new_connector(p)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _powershell(command: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
    return (out.stdout or "").strip()


def find_connector_app() -> Path | None:
    text = _powershell(f'(Get-ScheduledTask -TaskName "{TASK}").Actions | ForEach-Object {{ $_.Arguments + " " + $_.Execute }}')
    found = app_path_from(text)
    if found:
        return found
    from config import env
    return app_path_from(env("SCANNER_CONNECTOR_CMD", "") or "")


def stop_connector() -> None:
    # The pattern is spelled so this command's own text doesn't match it, and our own PID is skipped: otherwise
    # the PowerShell running this would find itself and stop itself.
    _powershell("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'ibkr_conn[e]ctor' } "
                "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")


def _port_open(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def wait_for_order_flow(port: int, seconds: float = 60) -> tuple[bool, bool]:
    """(up, knows order flow) - waits for the connector's port to open, then reads its route list. (/health needs
    your connector secret, so it can't be used to tell whether it is up.)"""
    deadline = time.monotonic() + seconds
    up = False
    while time.monotonic() < deadline:
        if _port_open(port):
            up = True
            break
        time.sleep(2)
    if not up:
        return False, False
    try:
        spec = urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=5).read().decode("utf-8", "replace")
        return True, "/market-data/order-flow" in spec
    except Exception:  # noqa: BLE001
        return True, False


def main(argv: list[str]) -> int:
    from local_connector import connector_port

    new = pick_download(Path.home() / "Downloads", argv[0] if argv else None)
    if new is None:
        print("I couldn't find the new connector file. On GitHub open topfan2026/tradeledger > services > "
              "ibkr_connector > app.py and click the download icon (Download raw file), then run this again.")
        return 1
    target = find_connector_app()
    if target is None or not target.parent.is_dir():
        print("I couldn't find your connector folder (the 'TradeLedger IBKR Connector' Windows task). "
              f"Copy {new} into it by hand instead.")
        return 1
    print(f"new file: {new}\nconnector: {target}")
    backup = target.with_name("app.py.old")
    if target.exists():
        shutil.copy2(target, backup if not backup.exists() else target.with_name(f"app.py.{int(time.time())}.old"))
        print("old app.py saved as", backup.name)
    shutil.copy2(new, target)
    print("new app.py copied in; restarting the connector...")
    stop_connector()
    time.sleep(2)
    subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True, text=True)
    up, flow = wait_for_order_flow(connector_port())
    if flow:
        print("DONE: the connector is running and knows order flow. Bubbles and order flow work from the next prices.")
        return 0
    if up:
        print("The connector is running but still doesn't list order flow - the file may not be the newest. "
              "Download app.py again and re-run this.")
        return 1
    print("The connector didn't come back within 60 seconds. Click 'Check setup (stream)' to start it, "
          f"or put the old file back: copy {backup.name} over app.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
