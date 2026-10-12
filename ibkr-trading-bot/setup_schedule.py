"""Register the bot's 11 Windows Task Scheduler tasks (user context, no admin). Idempotent (/F).

ET times are converted to this PC's local time when you run this script. If your local
timezone has different daylight-saving dates than New York, re-run it after either side
switches clocks.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
VENV_PY = (PROJECT_DIR / ".venv" / "Scripts" / "python.exe").resolve()
ET = ZoneInfo("America/New_York")

WEEKDAYS = "MON,TUE,WED,THU,FRI"
PREFILTER_TIMES = ["09:55", "10:25", "10:55", "11:25", "11:55", "12:25", "12:55"]


def et_to_local(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.now(ET).replace(hour=h, minute=m, second=0, microsecond=0).astimezone()


def short_date_format() -> str:
    """Translate the Windows short-date pattern (e.g. M/d/yyyy, yyyy/MM/dd) to strftime."""
    out = subprocess.run(["powershell", "-NoProfile", "-c", "(Get-Culture).DateTimeFormat.ShortDatePattern"],
                         capture_output=True, text=True).stdout.strip() or "MM/dd/yyyy"
    tokens = {"yyyy": "%Y", "yy": "%y", "MM": "%m", "M": "%m", "dd": "%d", "d": "%d"}
    fmt = re.sub(r"yyyy|yy|MM|M|dd|d", lambda m: tokens[m.group(0)], out)  # zero-padded is accepted
    return fmt


def script_cmd(script: str) -> str:
    return f'"{VENV_PY}" "{PROJECT_DIR / script}"'


def tasks() -> list[dict]:
    t = [
        {"name": "HT_LogRotate", "tr": script_cmd("rotate_logs.py"), "et": "09:25"},
        {"name": "HT_KeepAwake", "tr": "powercfg /change standby-timeout-ac 0", "et": "09:30"},
    ]
    for i, hhmm in enumerate(PREFILTER_TIMES, 1):
        t.append({"name": f"HT_Prefilter_{i:02d}", "tr": script_cmd("morning_prefilter.py"), "et": hhmm})
    t.append({"name": "HT_Cycle", "tr": script_cmd("cycle.py"), "et": "10:00", "minute": True})
    t.append({"name": "HT_Dashboard", "tr": script_cmd("compute_perf.py"), "et": "16:05"})
    if (PROJECT_DIR / "ibc" / "config.ini").exists():  # automatic TWS login is set up (SETUP_AUTOLOGIN.bat)
        pyw = VENV_PY.with_name("pythonw.exe")
        t.append({"name": "HT_TWSLogin", "et": "09:00",
                  "tr": f'"{pyw if pyw.exists() else VENV_PY}" "{PROJECT_DIR / "tws_login.py"}"'})
    return t


def main() -> int:
    if sys.platform != "win32" or not shutil.which("schtasks"):
        print("This script is for Windows Task Scheduler. On Mac/Linux use the cron lines in README.md.")
        return 1
    if not VENV_PY.exists():
        print(f"Missing {VENV_PY}. Create the venv first: python -m venv .venv")
        return 1

    date_fmt = short_date_format()
    ok = 0
    for task in tasks():
        local = et_to_local(task["et"])
        cmd = ["schtasks", "/create", "/tn", task["name"], "/tr", task["tr"], "/f"]
        if task.get("minute"):
            cmd += ["/sc", "MINUTE", "/mo", "5", "/sd", local.strftime(date_fmt), "/st", local.strftime("%H:%M")]
        else:
            cmd += ["/sc", "WEEKLY", "/d", WEEKDAYS, "/st", local.strftime("%H:%M")]
        r = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
            print(f"OK   {task['name']:<16} {task['et']} ET = {local:%H:%M} local")
        else:
            print(f"FAIL {task['name']:<16} {r.stderr.strip() or r.stdout.strip()}")

    r = subprocess.run(["schtasks", "/query", "/fo", "TABLE"], capture_output=True, text=True)
    lines = r.stdout.splitlines()
    print("\nBot tasks (name, next run, status):")
    print("\n".join(l for l in lines if l.startswith("HT_")))
    print(f"SCHEDULED: {ok}/{len(tasks())} tasks created. The bot will fire on its own starting next market open. Watch Telegram.")
    return 0 if ok == len(tasks()) else 1


if __name__ == "__main__":
    sys.exit(main())
