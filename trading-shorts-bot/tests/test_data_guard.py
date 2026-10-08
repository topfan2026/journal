from datetime import datetime, timedelta, timezone

import pytest

import data_guard
import ibkr
import live


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def make_guard(net=True, prices=(True, "SPY 500")):
    state = {"net": net, "prices": prices}
    clock = Clock()
    guard = data_guard.DataGuard(net=lambda: state["net"], prices=lambda: state["prices"], clock=clock)
    return guard, state, clock


def test_offline_only_waits_and_no_data_escalates():
    guard, state, clock = make_guard(net=False)
    calls = []
    fixes = dict(restart_gateway=lambda: calls.append("gateway"), restart_connector=lambda: calls.append("connector"),
                 reconnect_site=lambda: calls.append("site"))
    assert guard.check() == data_guard.OFFLINE
    assert guard.recover(**fixes) == "" and calls == []

    state["net"], state["prices"] = True, (False, "IBKR returned no prices")
    assert guard.check() == data_guard.NO_DATA
    assert guard.recover(**fixes) == "reconnected the website to IBKR"
    assert guard.recover(**fixes) == "restarted the scanner connector"
    assert guard.recover(**fixes) == "restarted IB Gateway"
    assert calls == ["site", "connector", "site", "gateway", "site"]
    # Gateway is restarted at most every DATA_GATEWAY_RESTART_MIN (5) minutes.
    assert guard.recover(**fixes) == "reconnected the website to IBKR"
    clock.t += 301
    assert guard.recover(**fixes) == "restarted IB Gateway"

    clock.t += 60
    assert guard.minutes_bad() > 5
    state["prices"] = (True, "SPY 500")
    assert guard.check() == data_guard.OK and guard.tries == 0 and guard.minutes_bad() == 0


@pytest.mark.parametrize("now,age_min,ok", [
    (datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc), 45, False),   # 7:30 New York, 45 min old: stale
    (datetime(2026, 10, 8, 11, 30, tzinfo=timezone.utc), 5, True),
    (datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc), 300, True),     # 2:00 New York: nothing trades yet
    (datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc), 2000, True),  # Saturday
])
def test_fresh_only_judged_in_the_extended_session(now, age_min, ok):
    assert ibkr.fresh(now - timedelta(minutes=age_min), now)[0] is ok
