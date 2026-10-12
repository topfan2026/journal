"""Scheduled weekdays at 9:00 ET with 'wake the computer': wakes the PC from sleep, keeps it
awake through the trading day, and makes sure TWS paper is logged in. At 16:10 ET it lets go,
so the PC can sleep again on its normal power settings.

Windows sends a timer-woken PC back to sleep after ~2 idle minutes unless a program asks it to
stay awake; this script is that program (SetThreadExecutionState), so no power settings change.
"""
from __future__ import annotations

import sys
import time
from datetime import time as dtime

from src import autologin
from src.common import now_et, ts
from src.notify import notify

STAY_AWAKE_UNTIL = dtime(16, 10)  # ET
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def hold_awake(on: bool) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def main() -> int:
    if now_et().weekday() >= 5 or now_et().time() >= STAY_AWAKE_UNTIL:
        return 0
    hold_awake(True)
    print(f"{ts()} holding the PC awake until {STAY_AWAKE_UNTIL:%H:%M} ET")
    try:
        time.sleep(20)  # let Wi-Fi/network reconnect after waking
        if not autologin.api_port_open():
            if autologin.configured():
                import tws_login
                tws_login.main()  # starts TWS with automatic paper login, Telegram on success/failure
            else:
                notify("TWS is not running", "The PC is awake for trading but TWS isn't open. Open TWS and log in to "
                                             "paper (or set up SETUP_AUTOLOGIN.bat to do it automatically).", "high")
        while now_et().time() < STAY_AWAKE_UNTIL:
            time.sleep(60)
    finally:
        hold_awake(False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
