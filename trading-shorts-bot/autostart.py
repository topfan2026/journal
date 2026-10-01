"""Start the live-stream scheduler (`live.py daemon`) automatically when you log in.

    Windows  a Task Scheduler task "LiveStreamBot" (at log on) running live_daemon.bat
    macOS    ~/Library/LaunchAgents/com.livestream.bot.plist (launchd, restarted if it stops)
    Linux    ~/.config/systemd/user/live-stream-bot.service (systemd --user)

It runs at log on, not at boot, because OBS and the browser need your desktop session.
The computer must be on and logged in (screen locked is fine) before LIVE_START.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config import BOT_DIR

TASK = "LiveStreamBot"
LABEL = "com.livestream.bot"
UNIT = "live-stream-bot.service"


def _python() -> str:
    return sys.executable


def windows_bat(bot_dir: Path = BOT_DIR, python: str | None = None) -> str:
    return f'@echo off\r\ncd /d "{bot_dir}"\r\n"{python or _python()}" live.py daemon\r\n'


def mac_plist(bot_dir: Path = BOT_DIR, python: str | None = None) -> str:
    from xml.sax.saxutils import escape
    log = Path("~/TradingShorts/logs/live-daemon.log").expanduser()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{escape(python or _python())}</string><string>live.py</string><string>daemon</string>
  </array>
  <key>WorkingDirectory</key><string>{escape(str(bot_dir))}</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict></plist>
"""


def systemd_unit(bot_dir: Path = BOT_DIR, python: str | None = None) -> str:
    return f"""[Unit]
Description=Daily live stream scheduler
After=graphical-session.target

[Service]
WorkingDirectory={bot_dir}
ExecStart="{python or _python()}" live.py daemon
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"{cmd[0]} failed")
    return proc.stdout.strip()


def install() -> str:
    if os.name == "nt":
        bat = BOT_DIR / "live_daemon.bat"
        bat.write_text(windows_bat(), encoding="utf-8")
        _run(["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "ONLOGON", "/RL", "LIMITED", "/TR", f'"{bat}"'])
        return f"Task Scheduler task '{TASK}' created - it starts when you log on"
    if sys.platform == "darwin":
        plist = Path(f"~/Library/LaunchAgents/{LABEL}.plist").expanduser()
        plist.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.write_text(mac_plist(), encoding="utf-8")
        _run(["launchctl", "load", str(plist)])
        return f"launchd agent {plist} installed and started"
    unit = Path(f"~/.config/systemd/user/{UNIT}").expanduser()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(systemd_unit(), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", UNIT])
    return f"systemd user service {UNIT} enabled and started"


def uninstall() -> str:
    if os.name == "nt":
        _run(["schtasks", "/Delete", "/F", "/TN", TASK])
        subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True)
        return f"Task Scheduler task '{TASK}' removed"
    if sys.platform == "darwin":
        plist = Path(f"~/Library/LaunchAgents/{LABEL}.plist").expanduser()
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True)
        return "launchd agent removed"
    subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], capture_output=True)
    Path(f"~/.config/systemd/user/{UNIT}").expanduser().unlink(missing_ok=True)
    return "systemd user service removed"


def installed() -> bool:
    if os.name == "nt":
        return subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True).returncode == 0
    if sys.platform == "darwin":
        return Path(f"~/Library/LaunchAgents/{LABEL}.plist").expanduser().exists()
    return Path(f"~/.config/systemd/user/{UNIT}").expanduser().exists()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    print(install() if action == "install" else uninstall() if action == "uninstall" else __doc__)
