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
from datetime import datetime, timezone
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


def command_port() -> int:
    return int(env_float("IBC_COMMAND_PORT", 7462))


def stop_gateway() -> bool:
    """Ask IBC to close IB Gateway (its command server, started by the bot's IBC config). False if
    Gateway wasn't started by the bot, or isn't running."""
    try:
        with socket.create_connection(("127.0.0.1", command_port()), timeout=5) as s:
            s.sendall(b"STOP\n")
            s.settimeout(5)
            try:
                s.recv(256)
            except OSError:
                pass
        return True
    except OSError:
        log.info("IB Gateway's IBC command port %s isn't open - close Gateway from its window", command_port())
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
        # Lets the bot close Gateway tidily (STOP) at the end of the Website data schedule; this PC only.
        "CommandServerPort": str(command_port()),
        "BindAddress": "127.0.0.1",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in settings.items()))
    tmp.replace(path)
    return path


def installed_gateways(tws: Path) -> list[str]:
    """Gateway versions installed under the Jts folder (ibgateway/1051 -> "1051"), oldest first."""
    folder = tws / "ibgateway"
    try:
        found = [d.name for d in folder.iterdir() if d.is_dir() and d.name.isdigit()]
    except OSError:
        return []
    return sorted(found, key=int)


def gateway_version(tws: Path, configured: str) -> str:
    """The Gateway version to start. IB Gateway updates itself into a new folder (e.g. 10.30 -> 10.51) and
    the old one may be removed; when the saved version isn't installed any more, use the newest that is."""
    installed = installed_gateways(tws)
    if not installed or configured in installed:
        return configured
    newest = installed[-1]
    log.warning("IB Gateway %s isn't installed in %s - using %s, the newest installed "
                "(set Gateway version to %s in the IB Gateway tab)", configured, tws / "ibgateway", newest, newest)
    return newest


def gateway_command(ini: Path) -> list[str]:
    custom = env("IBC_START_CMD")
    if custom:  # e.g. your own gatewaystart.sh / StartGateway.bat
        return shlex.split(custom, posix=os.name != "nt")
    ibc_path, version = require_env("IBC_PATH", "TWS_MAJOR_VRSN")
    ibc = Path(ibc_path).expanduser()
    if os.name == "nt":
        tws = Path(env("TWS_PATH", "C:/Jts") or "C:/Jts")
        return [str(ibc / "scripts" / "StartIBC.bat"), gateway_version(tws, version), "/Gateway", f"/TwsPath:{tws}",
                f"/IbcPath:{ibc}", f"/Config:{ini}", "/Mode:paper"]
    default_tws = "~/Applications" if sys.platform == "darwin" else "~/Jts"
    tws = Path(env("TWS_PATH", default_tws) or default_tws).expanduser()
    return [str(ibc / "scripts" / "ibcstart.sh"), gateway_version(tws, version), "--gateway", f"--tws-path={tws}",
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


# IBKR error codes: lost connection to IBKR's servers / market data farms, and "no permission" (can't judge).
LOST_CODES = {1100, 2103, 2105, 2110, 2157}
NO_PERMISSION_CODES = {162, 354, 10089, 10167, 10168}


def market_data_check(symbol: str | None = None, timeout: float | None = None, now: datetime | None = None) -> tuple[bool, str]:
    """The price check below, run on its own thread with its own event loop. Once the scanner's browser is
    open, the main thread already has an event loop running (Playwright), and IB's client refuses to connect
    inside one ("This event loop is already running"), which made a healthy Gateway look like it had no data."""
    import asyncio
    import threading

    out: list[tuple[bool, str]] = []

    def work():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            out.append(_market_data_check(symbol, timeout, now))
        except Exception as e:  # noqa: BLE001
            out.append((False, f"price check failed ({e or type(e).__name__})"))
        finally:
            loop.close()

    t = threading.Thread(target=work, daemon=True, name="market-data-check")
    t.start()
    t.join((timeout if timeout is not None else env_float("DATA_CHECK_TIMEOUT", 20)) + env_float("IB_CONNECT_TIMEOUT", 20) + 15)
    return out[0] if out else (False, "the price check didn't finish")


def _market_data_check(symbol: str | None = None, timeout: float | None = None, now: datetime | None = None) -> tuple[bool, str]:
    """Does IB Gateway actually return recent prices? A running Gateway whose port is open can still have lost
    its connection to IBKR (after an internet outage), which leaves the scanner and Autopilot with no data.
    Asks for the last day of 1-minute bars of SPY (any session) and, from 4:05 to 19:55 New York on weekdays,
    wants the newest bar to be at most DATA_STALE_MIN (30) minutes old. True when it can't judge (no data
    permission), so a missing subscription never holds the stream back."""
    from ib_async import IB, StartupFetch, Stock

    symbol = symbol or env("DATA_CHECK_SYMBOL", "SPY") or "SPY"
    timeout = env_float("DATA_CHECK_TIMEOUT", 20) if timeout is None else timeout
    ib = IB()
    codes: list[int] = []
    ib.errorEvent += lambda _req, code, _msg, *_rest: codes.append(int(code))
    try:
        ib.connect(host(), port(), clientId=int(env_float("IB_CHECK_CLIENT_ID", 18)), readonly=True,
                   timeout=env_float("IB_CONNECT_TIMEOUT", 20), fetchFields=StartupFetch(0))
    except Exception as e:  # noqa: BLE001
        return False, f"can't reach IB Gateway ({e or type(e).__name__})"
    try:
        bars = ib.reqHistoricalData(Stock(symbol, "SMART", "USD"), endDateTime="", durationStr="1 D",
                                    barSizeSetting="1 min", whatToShow="TRADES", useRTH=False, formatDate=2,
                                    timeout=timeout)
    except Exception as e:  # noqa: BLE001
        bars = []
        log.debug("market data check failed: %s", e)
    finally:
        ib.disconnect()
    if not bars:
        if NO_PERMISSION_CODES & set(codes):
            return True, "can't verify prices (no market data permission for the check) - assuming OK"
        if LOST_CODES & set(codes):
            return False, "IB Gateway has lost its connection to IBKR"
        return False, "IBKR returned no prices"
    last = bars[-1]
    when = last.date if isinstance(last.date, datetime) else None
    ok, message = fresh(when, now)
    return ok, message.format(symbol=symbol, price=last.close)


def fresh(when: datetime | None, now: datetime | None = None) -> tuple[bool, str]:
    """Whether the newest bar is recent enough for the time of day (only judged in the extended session)."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    now = (now or datetime.now(timezone.utc)).astimezone(ny)
    if when is None:
        return True, "{symbol} {price}"
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    age = (now - when.astimezone(ny)).total_seconds() / 60
    minutes = now.hour * 60 + now.minute
    in_session = now.weekday() < 5 and 4 * 60 + 5 <= minutes <= 19 * 60 + 55
    stamp = when.astimezone(ny).strftime("%H:%M")
    if in_session and age > env_float("DATA_STALE_MIN", 30):
        return False, f"prices are stale: newest {{symbol}} bar is from {stamp} New York ({age:.0f} min old)"
    return True, f"{{symbol}} {{price}} at {stamp} New York"
