"""Live-data guard: the stream and Autopilot are only useful with live prices.

After an internet outage IB Gateway can keep its port open while it has lost IBKR, the scanner connector's
tunnel can die, and the website keeps showing an old connection -- the stream would go live on an empty
scanner and Autopilot would run without data. This checks the real thing (internet, then recent prices from
IB Gateway) and fixes it step by step: reconnect the website, then restart the connector, then IB Gateway.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Callable

import ibkr
from config import env_bool, env_float

log = logging.getLogger(__name__)

OK, OFFLINE, NO_DATA = "ok", "offline", "no-data"
HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 53), ("www.google.com", 443))


def required() -> bool:
    """LIVE_REQUIRE_DATA (on by default): hold the stream until there are live prices, and fix lost data."""
    return env_bool("LIVE_REQUIRE_DATA", True)


def internet_up(timeout: float = 4.0) -> bool:
    for host, port in HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class DataGuard:
    """Remembers how long data has been missing and which fix comes next."""

    def __init__(self, net: Callable[[], bool] = internet_up,
                 prices: Callable[[], tuple[bool, str]] = ibkr.market_data_check,
                 clock: Callable[[], float] = time.monotonic):
        self.net, self.prices, self.clock = net, prices, clock
        self.state = OK
        self.detail = ""
        self.bad_since: float | None = None
        self.tries = 0
        self.last_gateway_restart = -1e9

    def check(self) -> str:
        if not self.net():
            state, detail = OFFLINE, "no internet connection"
        else:
            ok, detail = self.prices()
            state = OK if ok else NO_DATA
        if state == OK:
            self.bad_since, self.tries = None, 0
        elif self.bad_since is None:
            self.bad_since = self.clock()
        self.state, self.detail = state, detail
        return state

    def minutes_bad(self) -> float:
        return 0.0 if self.bad_since is None else (self.clock() - self.bad_since) / 60

    def recover(self, restart_gateway: Callable[[], object], restart_connector: Callable[[], object],
                reconnect_site: Callable[[], object]) -> str:
        """One step of the fix for the current state; returns what it did ('' when it can only wait)."""
        if self.state == OFFLINE:
            return ""  # nothing to fix on this PC; reconnect everything once the internet is back
        if self.state != NO_DATA:
            return ""
        self.tries += 1
        if self.tries == 1:
            reconnect_site()
            return "reconnected the website to IBKR"
        if self.tries == 2:
            restart_connector()
            reconnect_site()
            return "restarted the scanner connector"
        if self.clock() - self.last_gateway_restart >= env_float("DATA_GATEWAY_RESTART_MIN", 5) * 60:
            self.last_gateway_restart = self.clock()
            restart_gateway()
            reconnect_site()
            return "restarted IB Gateway"
        reconnect_site()
        return "reconnected the website to IBKR"
