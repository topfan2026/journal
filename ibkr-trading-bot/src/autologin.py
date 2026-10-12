"""Automatic TWS paper login using IBC (github.com/IbcAlpha/IBC, free and open source).

IBC starts TWS, fills in the paper username/password, clicks through the start-up dialogs and
keeps TWS running. Everything lives in <bot folder>/ibc (not in git, untouched by updates):
    ibc/             IBC itself (downloaded by setup_autologin.py)
    ibc/config.ini   your PAPER login, readable only by your Windows user
"""
from __future__ import annotations

import io
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from src.common import PROJECT_DIR, env_int, env_str

IBC_DIR = PROJECT_DIR / "ibc"
IBC_INI = IBC_DIR / "config.ini"
START_BAT = IBC_DIR / "StartTWS.bat"
JTS_DIR = Path(r"C:\Jts")

# Settings written into IBC's config.ini (besides the login).
IBC_SETTINGS = {
    "TradingMode": "paper",
    "AcceptIncomingConnectionAction": "accept",   # the "allow API connection?" pop-up
    "ReadOnlyApi": "no",
    "AcceptNonBrokerageAccountWarning": "yes",    # the "this is a paper account" warning
    "ExistingSessionDetectedAction": "primary",
    "MinimizeMainWindow": "yes",
    "AutoRestartTime": "11:45 PM",                # daily restart that keeps you logged in all week
    "OverrideTwsApiPort": "7497",
}


def configured() -> bool:
    return START_BAT.exists() and IBC_INI.exists() and "IbLoginId=" in IBC_INI.read_text(encoding="utf-8", errors="ignore")


def find_tws_version(jts: Path = JTS_DIR) -> tuple[str | None, str]:
    """IBC needs the STANDALONE ('offline') TWS, installed as C:\\Jts\\<version>\\tws.exe.
    Returns (major_version, note)."""
    versions = sorted((p.name for p in jts.glob("*") if p.is_dir() and p.name.isdigit() and (p / "tws.exe").exists()),
                      key=int, reverse=True) if jts.exists() else []
    if versions:
        return versions[0], f"Found TWS {versions[0]} in {jts / versions[0]}"
    if (jts / "tws.exe").exists():
        return None, ("Your TWS is the self-updating ('latest') edition, which IBC can't drive. Install the "
                      "'TWS Offline' (stable) edition from IBKR's website (search 'TWS offline installer'), "
                      "then run this setup again.")
    return None, "TWS not found in C:\\Jts. Install TWS (the 'Offline' stable edition) first."


def set_ini_values(text: str, values: dict[str, str]) -> str:
    """Set key=value lines in an IBC config.ini, keeping its comments; append missing keys."""
    lines = text.splitlines()
    pending = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    return "\n".join(lines) + "\n"


def set_bat_vars(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Set `set NAME=value` lines in StartTWS.bat. Returns (new_text, names_not_found)."""
    missing = []
    for name, value in values.items():
        pattern = re.compile(rf"^(set {re.escape(name)}=).*$", re.IGNORECASE | re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda m: m.group(1) + value, text, count=1)
        else:
            missing.append(name)
    return text, missing


def download_ibc(dest: Path = IBC_DIR) -> str:
    """Download the latest IBC for Windows from GitHub into dest. Returns the version."""
    req = urllib.request.Request("https://api.github.com/repos/IbcAlpha/IBC/releases/latest",
                                 headers={"User-Agent": "ibkr-trading-bot", "Accept": "application/vnd.github+json"})
    release = json.loads(urllib.request.urlopen(req, timeout=30).read())
    asset = next(a for a in release["assets"] if a["name"].startswith("IBCWin") and a["name"].endswith(".zip"))
    data = urllib.request.urlopen(urllib.request.Request(asset["browser_download_url"],
                                                         headers={"User-Agent": "ibkr-trading-bot"}), timeout=120).read()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        # if everything sits in one top-level folder, unpack its contents directly into dest
        prefix = ""
        if "StartTWS.bat" not in names:
            prefix = next((n[:-len("StartTWS.bat")] for n in names if n.endswith("/StartTWS.bat")), "")
        for name in names:
            if not name.startswith(prefix) or name == prefix:
                continue
            rel = name[len(prefix):]
            target = dest / rel
            if rel.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            if rel == "config.ini" and IBC_INI.exists():
                continue  # never overwrite an existing login
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    return release.get("tag_name", "?")


def lock_down(path: Path) -> None:
    """Windows: only the current user may read the file holding the password."""
    if sys.platform == "win32":
        import getpass
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
                       capture_output=True)


def api_port_open(timeout: float = 1) -> bool:
    try:
        with socket.create_connection((env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497)), timeout=timeout):
            return True
    except OSError:
        return False


def start_tws() -> bool:
    """Launch TWS through IBC (auto login). Returns False if IBC isn't set up."""
    if not configured():
        return False
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", str(START_BAT)], cwd=str(IBC_DIR), creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def wait_for_api(seconds: int = 240) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if api_port_open():
            return True
        time.sleep(3)
    return False
