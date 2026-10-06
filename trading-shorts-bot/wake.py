"""Wake the PC from sleep before the stream (Windows Task Scheduler wake timer).

Creates a per-user task "LiveStreamBot Wake" with "Wake the computer to run this task" on the
stream days, a few minutes before setup starts. It runs only while you are logged in (a sleeping
PC stays logged in), so it needs no admin rights or password. The task runs `power.py hold`,
which keeps the PC awake until the scheduler's setup has started - a timer wake otherwise drops
back to sleep after a minute or two.

A PC that was *shut down* can't be woken this way - use Sleep at night.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

TASK = "LiveStreamBot Wake"
DATA_TASK = "LiveStreamBot Wake (website data)"  # wakes the PC for the Website data schedule
BOT_DIR = Path(__file__).resolve().parent
HOLD_MIN = 30  # stay awake this long after waking: the scheduler's setup starts within it
DAY_TAGS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def wake_time(start: datetime, prep_min: float, early_min: float = 10) -> datetime:
    """When to wake: before setup (start - prep), with some extra minutes, in this PC's local time."""
    return (start - timedelta(minutes=prep_min + early_min)).astimezone()


def wake_plan(start: datetime, prep_min: float, weekdays: set[int]) -> tuple[datetime, set[int]]:
    """Wake time and weekdays in local time (waking before midnight moves the days back by one)."""
    at = wake_time(start, prep_min)
    shift = (at.date() - start.astimezone().date()).days
    return at, {(d + shift) % 7 for d in weekdays}


def pythonw() -> str:
    """The windowless python next to this one (so waking doesn't flash a console)."""
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return str(quiet if quiet.exists() else exe)


def task_xml(at: datetime, weekdays: set[int], python: str | None = None, bot_dir: Path = BOT_DIR,
             description: str = "Wakes the PC from sleep before the daily live stream (Live Stream Bot).") -> str:
    python = escape(python or pythonw())
    script = escape(str(bot_dir / "power.py"))
    days = "".join(f"<{DAY_TAGS[d]} />" for d in sorted(weekdays))
    boundary = at.replace(tzinfo=None, second=0, microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(description)}</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><DaysOfWeek>{days}</DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <WakeToRun>true</WakeToRun>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>false</StartWhenAvailable>
    <ExecutionTimeLimit>PT{HOLD_MIN + 10}M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{python}</Command><Arguments>"{script}" hold {HOLD_MIN}</Arguments><WorkingDirectory>{escape(str(bot_dir))}</WorkingDirectory></Exec></Actions>
</Task>
"""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def allow_wake_timers() -> bool:
    """Turn on Power Options > Sleep > Allow wake timers (plugged in and on battery) for the current plan."""
    ok = all(_run(["powercfg", flag, "SCHEME_CURRENT", "SUB_SLEEP", "RTCWAKE", "1"]).returncode == 0
             for flag in ("/SETACVALUEINDEX", "/SETDCVALUEINDEX"))
    return ok and _run(["powercfg", "/SETACTIVE", "SCHEME_CURRENT"]).returncode == 0


def install(start: datetime, prep_min: float, weekdays: set[int], task: str = TASK, what: str = "stream days") -> str:
    if os.name != "nt":
        return "waking from sleep is only set up on Windows"
    at, days = wake_plan(start, prep_min, weekdays)
    path = Path(tempfile.gettempdir()) / f"livestreambot-wake-{abs(hash(task)) % 10000}.xml"
    description = ("Wakes the PC from sleep before the Website data schedule (Live Stream Bot)." if task == DATA_TASK
                   else "Wakes the PC from sleep before the daily live stream (Live Stream Bot).")
    path.write_text(task_xml(at, days, description=description), encoding="utf-16")
    try:
        proc = _run(["schtasks", "/Create", "/F", "/TN", task, "/XML", str(path)])
    finally:
        path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "schtasks failed")
    timers = allow_wake_timers()
    when = at.strftime("%H:%M")
    return (f"the PC will wake from sleep at {when} on {what}"
            + ("" if timers else " - also turn on Power Options > Sleep > Allow wake timers"))


def uninstall(task: str = TASK) -> str:
    if os.name != "nt":
        return "nothing to remove"
    _run(["schtasks", "/Delete", "/F", "/TN", task])
    return "website data wake-up removed" if task == DATA_TASK else "wake-up removed"


def installed(task: str = TASK) -> bool:
    return os.name == "nt" and _run(["schtasks", "/Query", "/TN", task]).returncode == 0
