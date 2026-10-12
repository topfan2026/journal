"""Scheduled each weekday morning: make sure TWS paper is running and logged in (via IBC).
Does nothing if TWS is already up. Sends a Telegram message with the result."""
from __future__ import annotations

import sys

from src import autologin as al
from src.common import LOGS_DIR, append_jsonl, ts
from src.notify import notify


def main() -> int:
    if al.api_port_open():
        print(f"{ts()} TWS already running and logged in")
        return 0
    if not al.start_tws():
        print(f"{ts()} automatic login isn't set up (run SETUP_AUTOLOGIN.bat)")
        return 1
    ok = al.wait_for_api()
    append_jsonl(LOGS_DIR / "tws_login.jsonl", {"event": "tws_login", "ok": ok})
    if ok:
        notify("TWS logged in", "Paper TWS started and the API is ready for today.")
    else:
        notify("TWS LOGIN FAILED", "Paper TWS didn't come up within 4 minutes. Open TWS and log in by hand; "
                                   "see ibc\\Logs on the PC for the reason.", "high")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
