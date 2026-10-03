"""Helper programs the scanner WEBSITE needs before it can reach IB Gateway.

aialgopro.com talks to IB Gateway through the TradeLedger Python connector (localhost:8765) and,
from the live HTTPS site, a Cloudflare Tunnel to that port (e.g. https://ibkr.aialgopro.com).
Set the commands you use to start them; the bot starts each one that isn't already running
(in its own minimised window) before opening the website, and the watchdog restarts them.

    SCANNER_CONNECTOR_CMD   e.g.  python C:\\TradeLedger\\connector.py
    SCANNER_CONNECTOR_PORT  8765
    SCANNER_TUNNEL_CMD      e.g.  cloudflared tunnel run ibkr
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

from config import env, env_float

log = logging.getLogger("live")


def connector_port() -> int:
    return int(env_float("SCANNER_CONNECTOR_PORT", 8765))


def connector_up() -> bool:
    import ibkr
    return ibkr.port_open("127.0.0.1", connector_port())


def _exe_name(cmd: str) -> str:
    first = cmd.strip().split()[0].strip('"') if cmd.strip() else ""
    return os.path.basename(first).lower()


def tunnel_up(cmd: str) -> bool:
    """Is the tunnel program (e.g. cloudflared.exe) running?"""
    name = _exe_name(cmd)
    if not name:
        return True
    if not name.endswith(".exe") and os.name == "nt":
        name += ".exe"
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"], capture_output=True,
                                 text=True, timeout=15).stdout.lower()
            return name in out
        return subprocess.run(["pgrep", "-f", name.removesuffix(".exe")], capture_output=True).returncode == 0
    except Exception:
        return False


def _start(cmd: str, title: str) -> None:
    if os.name == "nt":
        # A minimised window of its own: keeps running if the bot restarts, and you can see its output.
        subprocess.Popen(f'start "{title}" /min cmd /k "{cmd}"', shell=True)
    else:
        subprocess.Popen(cmd, shell=True, start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def enabled() -> bool:
    return bool((env("SCANNER_CONNECTOR_CMD") or "").strip() or (env("SCANNER_TUNNEL_CMD") or "").strip())


def ensure(sleep=time.sleep) -> str:
    """Start the connector and the tunnel if needed; wait for the connector's port."""
    connector = (env("SCANNER_CONNECTOR_CMD") or "").strip()
    tunnel = (env("SCANNER_TUNNEL_CMD") or "").strip()
    done = []
    if connector:
        if connector_up():
            done.append(f"connector already running on port {connector_port()}")
        else:
            log.info("[connector] starting: %s", connector)
            _start(connector, "Scanner connector")
            deadline = time.monotonic() + env_float("SCANNER_CONNECTOR_WAIT", 60)
            while not connector_up():
                if time.monotonic() > deadline:
                    raise RuntimeError(f"the scanner connector didn't open port {connector_port()} - "
                                       f"check its window ('Scanner connector') for errors")
                sleep(2)
            done.append(f"connector started on port {connector_port()}")
    if tunnel:
        if tunnel_up(tunnel):
            done.append("tunnel already running")
        else:
            log.info("[connector] starting tunnel: %s", tunnel)
            _start(tunnel, "Scanner tunnel")
            sleep(env_float("SCANNER_TUNNEL_WAIT", 8))  # give the tunnel time to register with Cloudflare
            done.append("tunnel started")
    return ", ".join(done)


def healthy() -> bool:
    connector = (env("SCANNER_CONNECTOR_CMD") or "").strip()
    tunnel = (env("SCANNER_TUNNEL_CMD") or "").strip()
    return (not connector or connector_up()) and (not tunnel or tunnel_up(tunnel))
