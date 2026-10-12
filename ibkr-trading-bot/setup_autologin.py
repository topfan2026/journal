"""One-time setup for automatic TWS PAPER login (via IBC). Double-click SETUP_AUTOLOGIN.bat.

- Downloads IBC into <bot folder>/ibc
- Asks for your PAPER username and password and stores them in ibc/config.ini,
  readable only by your Windows user (never uploaded anywhere, untouched by app updates)
- Points IBC at your TWS and adds a weekday scheduled task that logs TWS in each morning
"""
from __future__ import annotations

import getpass
import subprocess
import sys

from src import autologin as al
from src.common import PROJECT_DIR


def ask(prompt: str, default: str = "") -> str:
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def main() -> int:
    print("\n=== Automatic TWS paper login (IBC) ===\n")
    if sys.platform != "win32":
        print("This setup is for Windows.")
        return 1

    version, note = al.find_tws_version()
    print(note)
    if not version:
        input("\nPress Enter to close...")
        return 1

    if al.START_BAT.exists():
        print(f"IBC already present in {al.IBC_DIR}")
    else:
        print("Downloading IBC (free, open source: github.com/IbcAlpha/IBC)...")
        print(f"Installed IBC {al.download_ibc()} into {al.IBC_DIR}")

    print("\nEnter your PAPER trading login (the paper username, NOT your live one).")
    print("It's saved only on this PC, in a file only your Windows user can read.")
    user = ask("Paper username")
    pw = getpass.getpass("Paper password (typing is hidden): ")
    if not user or not pw:
        print("Username and password are both needed. Nothing changed.")
        input("Press Enter to close...")
        return 1

    base = al.IBC_INI.read_text(encoding="utf-8", errors="ignore") if al.IBC_INI.exists() else ""
    al.IBC_INI.write_text(al.set_ini_values(base, {"IbLoginId": user, "IbPassword": pw, **al.IBC_SETTINGS}),
                          encoding="utf-8")
    al.lock_down(al.IBC_INI)

    bat, missing = al.set_bat_vars(al.START_BAT.read_text(encoding="utf-8", errors="ignore"), {
        "TWS_MAJOR_VRSN": version, "CONFIG": str(al.IBC_INI), "TRADING_MODE": "paper",
        "IBC_PATH": str(al.IBC_DIR), "TWS_PATH": str(al.JTS_DIR), "LOG_PATH": str(al.IBC_DIR / "Logs"),
        "TWOFA_TIMEOUT_ACTION": "restart",
    })
    al.START_BAT.write_text(bat, encoding="utf-8")
    if missing:
        print(f"Note: couldn't find {', '.join(missing)} in StartTWS.bat (IBC version change?). Tell Claude this line.")

    print("\nAdding the morning login task to Windows Task Scheduler...")
    subprocess.run([sys.executable, str(PROJECT_DIR / "setup_schedule.py")], cwd=PROJECT_DIR)

    if al.api_port_open():
        print("\nTWS is already running, so I won't start a second copy. Close TWS and run tws_login to test,")
        print("or just wait for tomorrow's 9:00 ET automatic login.")
    else:
        print("\nTesting now: starting TWS and logging in (this takes 1-3 minutes)...")
        al.start_tws()
        ok = al.wait_for_api()
        print("SUCCESS: TWS paper is logged in and the API is ready." if ok else
              "TWS didn't become ready. Check the TWS window for a message, and ibc\\Logs for details.")
    input("\nDone. Press Enter to close...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
