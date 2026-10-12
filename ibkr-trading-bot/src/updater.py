"""Self-update from GitHub: check for a newer version and install it in place.

Keeps everything that's yours: .env, .venv, trades.csv, logs, open_positions.json, watchlist,
and rules.json (your strategy settings). Only the bot's code files are replaced.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from src.common import PROJECT_DIR, env_str

VERSION_PATH = PROJECT_DIR / ".version"  # commit id of the installed version
SUBDIR = "ibkr-trading-bot"
KEEP = {".env", "rules.json"}  # never overwritten by an update
CHECK_EVERY = 30 * 60

_cache: dict = {"at": 0.0, "info": None}


def _repo() -> tuple[str, str]:
    return (env_str("UPDATE_REPO", "topfan2026/journal"), env_str("UPDATE_BRANCH", "claude/vigilant-goodall-oustn8"))


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ibkr-trading-bot-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def installed_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check(force: bool = False) -> dict:
    """{'available', 'latest', 'current', 'message', 'date'} or {'error'}; cached for 30 minutes."""
    if not force and _cache["info"] and time.monotonic() - _cache["at"] < CHECK_EVERY:
        return _cache["info"]
    repo, branch = _repo()
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{repo}/commits/{branch}"))
        latest = data["sha"]
        info = {"latest": latest[:7], "current": installed_version()[:7] or "unknown",
                "available": latest != installed_version(),
                "message": data["commit"]["message"].splitlines()[0][:140],
                "date": data["commit"]["committer"]["date"][:10]}
    except Exception as exc:
        info = {"available": False, "error": f"Couldn't check for updates ({type(exc).__name__})"}
    _cache.update(at=time.monotonic(), info=info)
    return info


def apply() -> str:
    """Download the latest version and copy its code over this folder. Returns a log for the UI."""
    repo, branch = _repo()
    log = []
    sha = json.loads(_get(f"https://api.github.com/repos/{repo}/commits/{branch}"))["sha"]
    log.append(f"Downloading version {sha[:7]}…")
    archive = zipfile.ZipFile(io.BytesIO(_get(f"https://codeload.github.com/{repo}/zip/{sha}", timeout=120)))

    old_requirements = (PROJECT_DIR / "requirements.txt").read_text(encoding="utf-8") \
        if (PROJECT_DIR / "requirements.txt").exists() else ""
    changed = 0
    for name in archive.namelist():
        parts = name.split("/", 2)  # "<repo>-<sha>/ibkr-trading-bot/<path>"
        if len(parts) < 3 or parts[1] != SUBDIR or not parts[2] or name.endswith("/"):
            continue
        rel = parts[2]
        dest = PROJECT_DIR / rel
        if rel in KEEP and dest.exists():
            continue
        data = archive.read(name)
        if dest.exists() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".updating")
        tmp.write_bytes(data)
        try:
            tmp.replace(dest)
        except PermissionError:  # file in use on Windows: retry once
            time.sleep(1)
            tmp.replace(dest)
        changed += 1
    log.append(f"Updated {changed} file(s). Kept your .env, rules.json and trade history.")

    new_requirements = (PROJECT_DIR / "requirements.txt").read_text(encoding="utf-8")
    if new_requirements != old_requirements:
        log.append("Installing new packages…")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
                            "-r", str(PROJECT_DIR / "requirements.txt")], capture_output=True, text=True)
        log.append("Packages installed." if r.returncode == 0 else f"pip failed:\n{(r.stdout + r.stderr)[-1500:]}")

    for cache in PROJECT_DIR.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    VERSION_PATH.write_text(sha + "\n", encoding="utf-8")
    _cache.update(at=0.0, info=None)
    log.append("Done. Close this window and open IBKR Trading Bot again to load the new version.")
    return "\n".join(log)
