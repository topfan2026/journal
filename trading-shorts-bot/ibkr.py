"""Gateway agent's plumbing: start IB Gateway (paper) through IBC and check the login.

IB Gateway has no login API, so the login is automated with IBC
(https://github.com/IbcAlpha/IBC), the standard open-source tool for starting
TWS / IB Gateway unattended. This module writes IBC's config.ini from .env
(owner-only permissions), launches Gateway in paper mode and waits for the API port.

Your scanner (aialgopro.com) connects to this Gateway, so the Gateway has to be
logged in before the browser agent opens the site.
"""
from __future__ import annotations

import logging
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

from config import env, env_bool, env_float, require_env

log = logging.getLogger(__name__)

PAPER_PREFIXES = ("DU", "DF")  # IBKR paper account ids


class IBKRError(Exception):
    pass


def host() -> str:
    return env("IB_HOST", "127.0.0.1") or "127.0.0.1"


def port() -> int:
    return int(env_float("IB_PORT", 4002))  # 4002 = IB Gateway paper


def port_open(h: str, p: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((h, p), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- gateway

def write_ibc_ini(path: Path) -> Path:
    """IBC config with the paper login. Kept owner-readable only; never commit it."""
    user, password = require_env("IB_USERNAME", "IB_PASSWORD")
    settings = {
        "IbLoginId": user,
        "IbPassword": password,
        "TradingMode": "paper",
        "OverrideTwsApiPort": str(port()),
        "ReadOnlyApi": "yes" if env_bool("IB_READ_ONLY", False) else "no",
        "AcceptNonBrokerageAccountWarning": "yes",
        "AcceptIncomingConnectionAction": "accept",
        "ExistingSessionDetectedAction": env("IB_EXISTING_SESSION", "primary"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in settings.items()))
    tmp.replace(path)
    return path


def gateway_command(ini: Path) -> list[str]:
    custom = env("IBC_START_CMD")
    if custom:  # e.g. your own gatewaystart.sh / StartGateway.bat
        return shlex.split(custom, posix=os.name != "nt")
    ibc_path, version = require_env("IBC_PATH", "TWS_MAJOR_VRSN")
    ibc = Path(ibc_path).expanduser()
    if os.name == "nt":
        tws = Path(env("TWS_PATH", "C:/Jts") or "C:/Jts")
        return [str(ibc / "scripts" / "StartIBC.bat"), version, "/Gateway", f"/TwsPath:{tws}",
                f"/IbcPath:{ibc}", f"/Config:{ini}", "/Mode:paper"]
    default_tws = "~/Applications" if sys.platform == "darwin" else "~/Jts"
    tws = Path(env("TWS_PATH", default_tws) or default_tws).expanduser()
    return [str(ibc / "scripts" / "ibcstart.sh"), version, "--gateway", f"--tws-path={tws}",
            f"--ibc-path={ibc}", f"--ibc-ini={ini}", "--mode=paper"]


def start_gateway(ini: Path, log_file: Path) -> dict:
    h, p = host(), port()
    if port_open(h, p):
        return {"started": False, "port": p, "note": "already running"}
    cmd = gateway_command(write_ibc_ini(ini))
    log.info("starting IB Gateway (paper) via IBC")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "ab") as out:
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
            else {"start_new_session": True}
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
    deadline = time.monotonic() + env_float("IB_START_TIMEOUT", 180)
    while time.monotonic() < deadline:
        if port_open(h, p):
            time.sleep(env_float("IB_SETTLE_SECONDS", 15))  # API accepts sockets before login finishes
            return {"started": True, "port": p, "pid": proc.pid}
        if proc.poll() not in (None, 0):
            break
        time.sleep(2)
    try:
        tail = "\n".join(log_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:])
    except OSError:
        tail = ""
    raise IBKRError(f"IB Gateway API port {p} did not open - see {log_file}"
                    + (f"\n--- last lines of that log ---\n{tail}" if tail else ""))


# --------------------------------------------------------------------------- connection

def connect():
    """Read-only API session, used by `live.py check` to prove the paper login works."""
    from ib_async import IB, StartupFetch

    ib = IB()
    ib.connect(host(), port(), clientId=int(env_float("IB_CLIENT_ID", 17)),
               readonly=True, timeout=env_float("IB_CONNECT_TIMEOUT", 20), fetchFields=StartupFetch(0))
    try:
        check_paper(ib.managedAccounts())
    except Exception:
        ib.disconnect()
        raise
    return ib


def check_paper(accounts: list[str]) -> None:
    """Refuse to run against a live account unless IB_REQUIRE_PAPER=false."""
    if not accounts:
        raise IBKRError("connected, but IBKR reported no accounts (login not finished?)")
    live = [a for a in accounts if not a.upper().startswith(PAPER_PREFIXES)]
    if live and env_bool("IB_REQUIRE_PAPER", True):
        raise IBKRError(f"account(s) {', '.join(live)} are not paper accounts - refusing to continue")
