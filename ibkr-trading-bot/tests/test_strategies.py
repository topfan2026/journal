from datetime import datetime, time, timedelta

import pandas as pd
import pytest

from src import strategies as st
from src.common import ET
from tests.test_logic import RULES, TODAY, make_daily

T0 = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 30, tzinfo=ET)


def bars(closes, start=T0, spread=0.2, prior_days=3, prior_close=100.0):
    """5-minute RTH bars: `prior_days` flat days, then today's closes. Last bar = still forming."""
    rows = []
    for d in range(prior_days, 0, -1):
        day0 = start - timedelta(days=d)
        for i in range(78):
            rows.append((day0 + timedelta(minutes=5 * i), prior_close, prior_close + .1, prior_close - .1, prior_close, 1000))
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        rows.append((start + timedelta(minutes=5 * i), o, max(o, c) + spread, min(o, c) - spread, c, 1000))
        prev = c
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


def cfg(kind, **params):
    s = {"id": kind + "_1", "type": kind, "enabled": True, "params": {**st.defaults_for(kind), "above_vwap": False, **params}}
    return st.config(s, RULES)


def run(kind, closes, price, **params):
    return st.evaluate(cfg(kind, **params), make_daily(), bars(closes), price, TODAY, RULES, time(11, 0))


def test_orb_fresh_breakout_passes_and_stops_at_range_low():
    closes = [100, 100.5, 99.8, 100.2, 100.4, 100.6, 101.5, 101.6]  # range = first 3 bars; break on bar 7
    res = run("orb", closes, 101.7, or_minutes="15", min_rvol=0)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["or_high"] == pytest.approx(100.7) and res["metrics"]["stop"] == pytest.approx(round(99.6 * 0.999, 2))


def test_orb_stale_breakout_fails():
    closes = [100, 100.5, 99.8, 101.5, 101.6, 101.7, 101.8, 101.9, 102.0, 102.1]
    res = run("orb", closes, 102.2, or_minutes="15", fresh_bars=2, min_rvol=0)
    assert not res["pass"] and any(r.startswith("breakout FAIL") for r in res["reasons"])


def test_orb_waits_for_range_to_finish():
    res = run("orb", [100, 100.5], 100.6, or_minutes="15")
    assert not res["pass"] and "not finished" in " ".join(res["reasons"])


def _first_signal(kind, closes_base, rising, **params):
    """Add rising bars one at a time; return the evaluation at the first bar that triggers."""
    closes = list(closes_base)
    for c in rising:
        closes.append(c)
        res = run(kind, closes + [c + 0.05], c + 0.1, **params)
        if res["pass"]:
            return res, len(closes)
    return None, len(closes)


def test_ema_cross_triggers_after_downtrend_reverses():
    down = [100 - i * 0.3 for i in range(30)]
    up = [down[-1] + i * 0.5 for i in range(1, 30)]
    res, n = _first_signal("ema_cross", down, up, fast=9, slow=21)
    assert res is not None, "fast EMA never crossed the slow EMA"
    assert res["metrics"]["fast_ema"] > res["metrics"]["slow_ema"] and res["metrics"]["stop"] < up[-1]


def test_price_cross_ema_triggers():
    down = [100 - i * 0.2 for i in range(25)]
    up = [down[-1] + i * 0.4 for i in range(1, 20)]
    res, _ = _first_signal("price_cross_ema", down, up, ema=20)
    assert res is not None and res["metrics"]["ema"] < res["metrics"]["price"]


def test_ema_bounce_needs_uptrend_touch_and_trigger():
    up = [100 + i * 0.25 for i in range(40)]
    e20 = st.ema(pd.Series(([100.0] * 234) + up), 20).iloc[-1]
    dip = [up[-1] - 0.6, e20 + 0.05, e20 + 0.4]   # pull back to the EMA, then a bar closing back up
    closes = up + dip
    res = run("ema_bounce", closes + [closes[-1]], closes[-1] + 0.8, ema=20, trend_ema=50, touch_pct=0.3)
    assert res["pass"], res["reasons"]
    flat = [100.0] * 45
    assert not run("ema_bounce", flat + [100.0], 100.5)["pass"]  # no uptrend


def test_trend_join_wraps_existing_filters():
    from tests.test_logic import make_intraday
    intra = make_intraday()
    price = float(intra["High"].iloc[:-1].max()) + 0.5
    s = {"id": st.TREND_JOIN_ID, "type": "trend_join", "enabled": True}
    res = st.evaluate(st.config(s, RULES), make_daily(), intra, price, TODAY, RULES, time(11, 0))
    assert res["pass"] and res["metrics"]["stop"] == pytest.approx(103.0 * 0.99)


def test_store_defaults_and_coercion(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STORE", tmp_path / "strategies.json")
    items = st.load()
    assert items[0]["id"] == st.TREND_JOIN_ID and items[0]["enabled"]
    vals = st.coerce("orb", {"or_minutes": "30", "fresh_bars": "99", "above_vwap": "false", "earliest_entry_et": "9:50",
                             "stop_rule": "bogus", "risk_pct": "5"})
    assert vals == {"or_minutes": "30", "fresh_bars": 6, "above_vwap": False, "earliest_entry_et": "09:50", "risk_pct": 2}
    items.append({"id": st.new_id("orb", items), "type": "orb", "name": "ORB", "enabled": True, "params": vals})
    st.save(items)
    again = st.load()
    assert again[1]["id"] == "orb_1" and again[1]["params"]["or_minutes"] == "30"
    assert again[1]["params"]["max_or_range_pct"] == 3.0  # missing settings filled from defaults


def test_trend_join_values_roundtrip():
    vals = st.trend_join_values(RULES)
    assert vals["D3_min_gap_pct_from_prior_close"] == 3.0 and vals["earliest_entry_et"] == "10:05"
