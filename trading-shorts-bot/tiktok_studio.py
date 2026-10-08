"""TikTok agent: where the stream goes (YouTube, TikTok or both), and the two ways to reach TikTok.

Where the stream goes (STREAM_TO, or `live.py run --to ...` / the app's "TikTok live now" button):
  youtube   OBS -> YouTube only (the default)
  tiktok    TikTok only, on its own: no YouTube broadcast is created
  both      OBS -> YouTube, and TikTok at the same time through TikTok LIVE Studio

How TikTok is reached (TIKTOK_METHOD):
  studio    TikTok LIVE Studio. Works for every account that can go LIVE, but it has no remote
            control: the bot opens it and reminds you, and the one click on "Go LIVE" stays yours.
            Closing LIVE Studio at the end time ends the TikTok LIVE.
  rtmp      OBS streams straight to TikTok with the server URL and stream key from TikTok LIVE
            Center. Fully automatic, but TikTok only gives stream keys to some accounts. OBS sends
            to one place at a time, so this works with "tiktok" and not with "both".

.env (all in the app's TikTok tab):
  STREAM_TO=youtube|tiktok|both   where the scheduled stream goes
  TIKTOK_METHOD=studio|rtmp
  TIKTOK_RTMP_SERVER=rtmp://...    from TikTok LIVE Center (rtmp method)
  TIKTOK_STREAM_KEY=...            secret, from TikTok LIVE Center (rtmp method)
  TIKTOK_STUDIO_PATH=...exe        TikTok LIVE Studio program
  TIKTOK_STUDIO_REMIND=true        pop up a reminder to press Go LIVE
  TIKTOK_STUDIO_CLOSE_AT_END=true  close LIVE Studio (ending the TikTok LIVE) at the end time
  TIKTOK_STUDIO=true               older setting: same as STREAM_TO=both when STREAM_TO is not set
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from config import ConfigError, env, env_bool

log = logging.getLogger(__name__)

REMINDER = ("YouTube is live.\n\nIn TikTok LIVE Studio, check the preview shows the scanner "
            "(LIVE BOT - Scanner window) and click Go LIVE.")
REMINDER_ALONE = ("The scanner is ready for TikTok.\n\nIn TikTok LIVE Studio, check the preview shows the "
                  "scanner (LIVE BOT - Scanner window) and click Go LIVE.")

DESTINATIONS = ("youtube", "tiktok", "both")
METHODS = ("studio", "rtmp")


def destination(override: str | None = None) -> str:
    """youtube | tiktok | both. An explicit choice (button / --to) wins over the saved setting."""
    value = (override or env("STREAM_TO") or "").strip().lower()
    if not value:  # before STREAM_TO existed, TIKTOK_STUDIO=true meant "YouTube and TikTok together"
        return "both" if env_bool("TIKTOK_STUDIO", False) else "youtube"
    if value not in DESTINATIONS:
        raise ConfigError(f"STREAM_TO must be one of {', '.join(DESTINATIONS)} (got {value!r})")
    return value


def to_youtube(dest: str) -> bool:
    return dest in ("youtube", "both")


def to_tiktok(dest: str) -> bool:
    return dest in ("tiktok", "both")


def method() -> str:
    value = (env("TIKTOK_METHOD") or "studio").strip().lower()
    if value not in METHODS:
        raise ConfigError(f"TIKTOK_METHOD must be studio or rtmp (got {value!r})")
    return value


def check_destination(dest: str) -> None:
    """Refuse a combination that can't work, before anything is started."""
    if not to_tiktok(dest):
        return
    if method() == "rtmp":
        if dest == "both":
            raise ConfigError("OBS streams to one place at a time: to stream to YouTube and TikTok together, "
                              "set TikTok to use TikTok LIVE Studio (TIKTOK_METHOD=studio)")
        rtmp_target()


def rtmp_target() -> dict:
    """OBS stream settings for TikTok (rtmp method)."""
    server, key = (env("TIKTOK_RTMP_SERVER") or "").strip(), (env("TIKTOK_STREAM_KEY") or "").strip()
    if not server or not key:
        raise ConfigError("TikTok by stream key needs TIKTOK_RTMP_SERVER and TIKTOK_STREAM_KEY "
                          "(both from TikTok LIVE Center)")
    if not server.lower().startswith(("rtmp://", "rtmps://")):
        raise ConfigError("TIKTOK_RTMP_SERVER must start with rtmp:// or rtmps://")
    return {"server": server, "key": key}


def uses_studio(dest: str) -> bool:
    return to_tiktok(dest) and method() == "studio"


def enabled() -> bool:
    """Is TikTok LIVE Studio part of the saved setup?"""
    try:
        return uses_studio(destination())
    except ConfigError:
        return False


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
        ctypes.windll.user32.MessageBoxW(None, message, "AiAlgobot - TikTok",
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
