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


def frame(closes, vols, start=T0, spread=0.15):
    rows, prev = [], closes[0]
    for i, (c, v) in enumerate(zip(closes, vols)):
        rows.append((start + timedelta(minutes=5 * i), prev, max(prev, c) + spread, min(prev, c) - spread, c, v))
        prev = c
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


def ht(kind, df, price, symbol="TST", daily=None, **params):
    return st.evaluate(cfg(kind, **params), daily if daily is not None else make_daily(), df, price, TODAY, RULES,
                       time(11, 0), symbol=symbol)


def test_ht_vwap_reclaim_on_volume_push():
    closes = [100 + i * 0.02 for i in range(6)] + [99.2 - i * 0.05 for i in range(8)] + [100.6, 100.8]
    vols = [1000] * 14 + [3000, 1500]  # the reclaim bar trades 3x the average
    df = frame(closes + [100.9], vols + [800])
    res = ht("ht_vwap_reclaim", df, 100.95, mode="reclaim")
    assert res["pass"], res["reasons"]
    assert res["metrics"]["stop"] < res["metrics"]["vwap"]  # never right on VWAP
    weak = frame(closes + [100.9], [1000] * 14 + [1100, 1000] + [800])  # same move without the volume push
    assert not ht("ht_vwap_reclaim", weak, 100.95, mode="reclaim")["pass"]


def test_ht_vwap_pullback_as_selling_dries_up():
    run_up = [100 + i * 0.25 for i in range(14)]           # trending above VWAP
    dip = [102.1, 101.75, 102.05]  # quiet pullback toward VWAP (~101.6), then a green bar back up
    closes = run_up + dip
    vols = [2000] * 14 + [700, 600, 900]
    df = frame(closes + [closes[-1] + 0.05], vols + [500])
    vw = st.vwap(df)
    res = ht("ht_vwap_reclaim", df, closes[-1] + 0.1, mode="pullback", touch_pct=0.3)
    assert res["pass"], (res["reasons"], vw)
    assert res["metrics"]["stop"] < vw
    loud = frame(closes + [closes[-1] + 0.05], [2000] * 14 + [4000, 3800, 3000] + [500])  # heavy selling into VWAP
    assert not ht("ht_vwap_reclaim", loud, closes[-1] + 0.1, mode="pullback", touch_pct=0.3)["pass"]


def test_ht_buy_dip_at_marked_support():
    closes = [104, 103, 102, 101.2, 100.6, 100.4, 100.5, 100.6]  # sells off into support, then stops making lows
    df = frame(closes + [100.6], [1000] * 9, spread=0.1)
    res = ht("ht_buy_dip", df, 100.6, symbol="NVDA", levels="NVDA:100.3, AMD:150", stable_bars=2)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["support"] == 100.3 and res["metrics"]["stop"] == pytest.approx(100.2)
    far = ht("ht_buy_dip", df, 101.8, symbol="NVDA", levels="NVDA:100.3")
    assert not far["pass"] and any(r.startswith("near support FAIL") for r in far["reasons"])
    none = ht("ht_buy_dip", df, 100.6, symbol="MSFT", levels="NVDA:100.3", auto_level=False)
    assert not none["pass"] and "no support level" in " ".join(none["reasons"])


def test_ht_buy_dip_auto_breakout_level_needs_a_runup():
    days = pd.bdate_range(end=TODAY - timedelta(days=1), periods=40)
    base = [100 + (i % 3) * 0.5 for i in range(30)]               # base topping at ~101.4
    run = [102, 106, 110, 115, 121, 124, 120, 114, 108, 102.5]   # +20%+ run, then the dip back
    closes = base + run
    daily = pd.DataFrame({"Open": closes, "High": [c + 0.4 for c in closes], "Low": [c - 0.4 for c in closes],
                          "Close": closes, "Volume": 1e6}, index=days)
    df = frame([103, 102.4, 101.9, 101.6, 101.7, 101.8, 101.8], [1000] * 7, spread=0.1)
    res = ht("ht_buy_dip", df, 101.8, daily=daily, symbol="XYZ", levels="", runup_days=10, base_days=30, stable_bars=2)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["support"] == pytest.approx(101.4)
    flat = daily.copy()
    flat[["Open", "High", "Low", "Close"]] = 101
    assert not ht("ht_buy_dip", df, 101.8, daily=flat, symbol="XYZ", runup_days=10, base_days=30)["pass"]


def test_levels_parse_and_watch_list():
    assert st.parse_levels("nvda:182.5; PLTR : 171, bad, AMD:x") == {"NVDA": 182.5, "PLTR": 171.0}
    c = cfg("ht_buy_dip", tickers="META", levels="NVDA:182.5")
    assert c["tickers"] == ["META", "NVDA"] and c["universe"] == "custom"


def one_min(pre, rth, day=TODAY):
    """Premarket 1-min bars from 8:00 + regular-hours 1-min bars from 9:30 (last one = still forming).
    Each item is (open, high, low, close)."""
    rows = []
    for i, (o, h, l, c) in enumerate(pre):
        rows.append((datetime(day.year, day.month, day.day, 8, 0, tzinfo=ET) + timedelta(minutes=i), o, h, l, c, 100))
    for i, (o, h, l, c) in enumerate(rth):
        rows.append((datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET) + timedelta(minutes=i), o, h, l, c, 1000))
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


PRE = [(100, 101.0, 99.5, 100.2), (100.2, 100.8, 99.0, 99.8), (99.8, 100.5, 99.6, 100.1)]  # PM high 101, low 99


def pm(rth, price, now=None, **params):
    """Evaluate at `now` (default: 20 s into the last, still-forming candle)."""
    bars = one_min(PRE, rth)
    if now is None:
        last = bars.index[-1]
        now = (last + timedelta(seconds=20)).time()
    five = bars  # 5-minute frame only feeds the common filters here
    return st.evaluate(cfg("pm_break", min_rvol=0, **params), make_daily(), five, price, TODAY, RULES, now, bars_1m=bars)


def test_pm_breakout_enters_on_second_close_above_with_stop_under_that_candle():
    rth = [(100.2, 100.6, 100.0, 100.5), (100.5, 101.4, 100.4, 101.3),  # 2nd candle: first close above 101 (the break)
           (101.3, 101.6, 101.05, 101.5),                               # 3rd: stays above -> confirmed
           (101.5, 101.7, 101.4, 101.6)]                                # forming
    res = pm(rth, 101.6)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["side"] == "long" and res["metrics"]["pm_high"] == 101.0
    assert res["metrics"]["stop"] == pytest.approx(101.04)  # low of the confirming candle - 1 cent
    # one candle later it's no longer fresh (fresh_bars = 1)
    late = pm(rth[:-1] + [(101.5, 101.8, 101.3, 101.7), (101.7, 101.8, 101.6, 101.7)], 101.7)
    assert not late["pass"]
    # only one close above so far: wait
    early = pm(rth[:2] + [(101.3, 101.4, 101.0, 101.2)], 101.3)
    assert not early["pass"] and "no fresh confirmed break" in " ".join(early["reasons"])


def test_pm_breakdown_goes_short_with_stop_above_the_candle():
    rth = [(99.6, 99.8, 99.3, 99.4), (99.4, 99.5, 98.7, 98.8),   # first close below 99 (the break)
           (98.8, 98.95, 98.5, 98.6),                            # 2nd stays below -> confirmed
           (98.6, 98.7, 98.4, 98.5)]                             # forming
    res = pm(rth, 98.5)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["side"] == "short" and res["metrics"]["stop"] == pytest.approx(98.96)
    assert not pm(rth, 98.5, direction="long")["pass"]  # long-only setting ignores breakdowns


def test_pm_break_needs_premarket_and_respects_vwap_side():
    bars = one_min([], [(100, 100.5, 99.5, 100.2), (100.2, 100.4, 100, 100.3)])
    res = st.evaluate(cfg("pm_break", min_rvol=0), make_daily(), bars, 100.3, TODAY, RULES, time(9, 32, 20), bars_1m=bars)
    assert not res["pass"] and "no premarket trading" in " ".join(res["reasons"])
    rth = [(100.2, 100.6, 100.0, 100.5), (100.5, 101.4, 100.4, 101.3), (101.3, 101.6, 101.05, 101.5), (101.5, 101.7, 101.4, 101.6)]
    res = pm(rth, 101.6, above_vwap=True)
    assert any(r.startswith("vwap") for r in res["reasons"])



def test_pm_break_uses_the_clock_not_the_last_candle():
    rth = [(100.2, 100.6, 100.0, 100.5), (100.5, 101.4, 100.4, 101.3), (101.3, 101.6, 101.05, 101.5)]
    # Yahoo lagging: the forming 9:33 candle isn't published yet, but at 9:33:20 the 9:32 candle IS complete
    res = pm(rth, 101.55, now=time(9, 33, 20))
    assert res["pass"], res["reasons"]
    assert res["metrics"]["break_time"] == "09:31" and res["metrics"]["confirm_time"] == "09:32"
    # the same data seen two minutes later (lagging feed / slow cycle): too late, no chasing
    late = pm(rth, 101.9, now=time(9, 35, 10))
    assert not late["pass"] and "too late" in " ".join(late["reasons"])


def test_pm_break_ignores_a_gap_beyond_the_level():
    # 9:30 candle opens and stays above the 101 premarket high: never traded through it -> not a break
    rth = [(101.5, 101.9, 101.3, 101.8), (101.8, 102.0, 101.6, 101.9), (101.9, 102.1, 101.8, 102.0)]
    res = pm(rth, 102.0)
    assert not res["pass"] and "a gap, not a break" in " ".join(res["reasons"])
    assert pm(rth, 102.0, require_cross=False)["pass"]  # the old behaviour, if wanted


def test_pm_break_settings_shown_in_the_form():
    keys = [f["k"] for f in st.fields_for("pm_break")]
    assert "stop_buffer_pct" not in keys and {"require_cross", "max_slip_R"} <= set(keys)
    assert "stop_buffer_pct" in [f["k"] for f in st.fields_for("orb")]
    assert cfg("pm_break")["max_slip_R"] == pytest.approx(0.2)


RTH_LONG = [(100.2, 100.6, 100.0, 100.5), (100.5, 101.4, 100.4, 101.3), (101.3, 101.6, 101.05, 101.5), (101.5, 101.7, 101.4, 101.6)]


def test_pm_break_stop_under_the_premarket_high_itself():
    res = pm(RTH_LONG, 101.6, stop_rule="level")
    assert res["pass"] and res["metrics"]["stop"] == pytest.approx(100.99)  # PM high 101 - 1 cent
    rth = [(99.6, 99.8, 99.3, 99.4), (99.4, 99.5, 98.7, 98.8), (98.8, 98.95, 98.5, 98.6), (98.6, 98.7, 98.4, 98.5)]
    short = pm(rth, 98.5, stop_rule="level")
    assert short["metrics"]["side"] == "short" and short["metrics"]["stop"] == pytest.approx(99.01)  # PM low 99 + 1 cent


def test_pm_break_min_stop_distance_widens_a_tight_stop():
    res = pm(RTH_LONG, 101.6, min_stop_pct=1.0)  # candle stop 101.04 is only 0.55% away -> moved to 1%
    assert res["pass"] and res["metrics"]["stop"] == pytest.approx(100.58)
    assert res["metrics"]["stop_widened_from"] == pytest.approx(101.04)
    assert pm(RTH_LONG, 101.6, min_stop_pct=0)["metrics"]["stop"] == pytest.approx(101.04)  # off
