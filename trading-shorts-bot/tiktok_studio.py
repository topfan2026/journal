"""TikTok agent: open TikTok LIVE Studio at go-live time, remind you to press Go LIVE, close it at the end.

TikTok only hands out RTMP stream keys to some accounts, so OBS can't stream there for most
people. TikTok LIVE Studio can, but it has no remote control, so the one click on its
"Go LIVE" button stays yours. Closing LIVE Studio at the end time ends the TikTok LIVE.

.env (all in the app's TikTok tab):
  TIKTOK_STUDIO=true              use this agent
  TIKTOK_STUDIO_PATH=...exe       TikTok LIVE Studio program
  TIKTOK_STUDIO_REMIND=true       pop up a reminder when YouTube goes live
  TIKTOK_STUDIO_CLOSE_AT_END=true close LIVE Studio (ending the TikTok LIVE) at the end time
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from config import env, env_bool

log = logging.getLogger(__name__)

REMINDER = ("YouTube is live.\n\nIn TikTok LIVE Studio, check the preview shows the scanner "
            "(LIVE BOT - Scanner window) and click Go LIVE.")


def enabled() -> bool:
    return env_bool("TIKTOK_STUDIO", False)


def exe_path() -> Path | None:
    path = env("TIKTOK_STUDIO_PATH")
    return Path(path).expanduser() if path else None


def find_exe() -> Path | None:
    """Look for TikTok LIVE Studio in the usual install folders (Windows)."""
    roots = [os.environ.get(k) for k in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)", "APPDATA")]
    for root in filter(None, roots):
        base = Path(root)
        for pattern in ("*/TikTok*.exe", "*/*/TikTok*.exe", "*/*/*/TikTok*.exe"):
            for hit in base.glob(pattern):
                name = hit.name.lower().replace(" ", "")
                if "live" in name and "studio" in name and "uninst" not in name:
                    return hit
    return None


def running() -> bool:
    exe = exe_path()
    if exe is None or os.name != "nt":
        return False
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe.name}", "/NH"],
                         capture_output=True, text=True).stdout
    return exe.name.lower() in out.lower()


def open_studio() -> str:
    exe = exe_path()
    if exe is None:
        return "TIKTOK_STUDIO_PATH is not set - pick TikTok LIVE Studio in the TikTok tab"
    if not exe.exists():
        return f"TikTok LIVE Studio not found at {exe}"
    if running():
        return "TikTok LIVE Studio is already open"
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([str(exe)], cwd=str(exe.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    return "opened TikTok LIVE Studio"


def remind(message: str = REMINDER) -> None:
    """A topmost pop-up that doesn't block the bot (Windows); elsewhere just the log line."""
    log.warning("[tiktok] %s", message.replace("\n\n", " "))
    if os.name != "nt" or not env_bool("TIKTOK_STUDIO_REMIND", True):
        return

    def show():
        import ctypes
        MB_OK, MB_ICONINFORMATION, MB_TOPMOST, MB_SETFOREGROUND = 0x0, 0x40, 0x40000, 0x10000
        ctypes.windll.user32.MessageBoxW(None, message, "Live Stream Bot - TikTok",
                                         MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND)
    threading.Thread(target=show, daemon=True).start()


def close_studio() -> str:
    exe = exe_path()
    if exe is None or os.name != "nt" or not running():
        return "TikTok LIVE Studio is not open"
    subprocess.run(["taskkill", "/IM", exe.name], capture_output=True)  # polite close first
    if running():
        subprocess.run(["taskkill", "/F", "/IM", exe.name], capture_output=True)
    return "closed TikTok LIVE Studio (the TikTok LIVE ends)"
