import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import compute_perf
import cycle
import morning_prefilter
from src import common
from src.common import ET
from src.filters import compute_rvol, evaluate_filters, initial_stop, position_size, swing_lows

RULES = json.loads(common.RULES_PATH.read_text())
TODAY = date(2026, 10, 12)  # a Monday


def make_daily(n=220, prior_close=100.0, prior_high=101.0, trend=0.1):
    days = pd.bdate_range(end=TODAY - timedelta(days=1), periods=n)
    closes = np.linspace(prior_close - trend * n, prior_close, n)
    df = pd.DataFrame({"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": 1e6}, index=days)
    df.iloc[-1, df.columns.get_loc("High")] = prior_high
    return df


def make_intraday(today_open=104.0, pm_high=104.5, today_vol=3000, prior_vol=1000, n_today=10):
    rows = []
    for k in range(1, 15):  # 14 prior days of RTH bars
        d = TODAY - timedelta(days=k)
        for i in range(78):
            t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET) + timedelta(minutes=5 * i)
            rows.append((t, 99, 100, 98, 99, prior_vol))
    for i in range(12):  # premarket 8:00-9:00
        t = datetime(TODAY.year, TODAY.month, TODAY.day, 8, 0, tzinfo=ET) + timedelta(minutes=5 * i)
        rows.append((t, 103, pm_high, 102.5, 103, 500))
    for i in range(n_today):
        t = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 30, tzinfo=ET) + timedelta(minutes=5 * i)
        o = today_open + i * 0.2
        rows.append((t, o, o + 0.3, o - 0.3 if i else today_open - 1.0, o + 0.1, today_vol))
    df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t").sort_index()
    return df


def test_all_filters_pass():
    intra = make_intraday()
    price = float(intra["High"].iloc[:-1].max()) + 0.5
    res = evaluate_filters(make_daily(), intra, price, TODAY, RULES)
    assert res["pass"], res["reasons"]
    assert res["metrics"]["low_of_day"] == pytest.approx(103.0)
    assert res["metrics"]["rvol"] == pytest.approx(3.0)


def test_small_gap_fails_d3():
    res = evaluate_filters(make_daily(), make_intraday(today_open=101.0), 110, TODAY, RULES)
    assert not res["pass"]
    assert any(r.startswith("D3 FAIL") for r in res["reasons"])


def test_below_sma200_fails_d2():
    res = evaluate_filters(make_daily(trend=-0.1), make_intraday(), 110, TODAY, RULES)
    assert any(r.startswith("D2 FAIL") for r in res["reasons"])


def test_not_above_hod_fails_i2():
    intra = make_intraday()
    res = evaluate_filters(make_daily(), intra, float(intra["High"].iloc[:-1].max()) - 0.1, TODAY, RULES)
    assert any(r.startswith("I2 FAIL") for r in res["reasons"])


def test_low_rvol_fails_i3():
    res = evaluate_filters(make_daily(), make_intraday(today_vol=1500), 200, TODAY, RULES)
    assert any(r.startswith("I3 FAIL") for r in res["reasons"])


def test_insufficient_history():
    res = evaluate_filters(make_daily(n=50), make_intraday(), 110, TODAY, RULES)
    assert not res["pass"] and "insufficient" in res["reasons"][0]


def test_rvol_same_time_of_day():
    assert compute_rvol(make_intraday(today_vol=2000), TODAY, 14) == pytest.approx(2.0)


def test_sizing_caps():
    # risk $250 / R $1 = 250 sh, but 10% cap $2500 / $100 = 25 sh
    assert position_size(100, 99, 25000, 1.0, 10, 2500) == 25
    # risk-limited: R $20 -> 12 sh
    assert position_size(100, 80, 25000, 1.0, 10, 2500) == 12
    assert position_size(100, 101, 25000, 1.0, 10, 2500) == 0
    assert initial_stop(50.0) == pytest.approx(49.5)


def test_swing_lows():
    idx = pd.date_range("2026-10-12 10:00", periods=7, freq="5min", tz=ET)
    bars = pd.DataFrame({"Low": [10, 9, 8, 9, 10, 7.5, 11]}, index=idx)
    assert swing_lows(bars) == [(idx[2], 8.0)]  # idx[5] lacks 2 bars on its right


@pytest.mark.parametrize("hhmm,wd,expected", [
    ("09:59", 0, "too_early"), ("10:00", 0, "manage_only"), ("10:05", 0, "ok"), ("15:30", 0, "ok"),
    ("15:31", 0, "manage_only"), ("15:51", 0, "force_close"), ("16:00", 0, "closed"), ("12:00", 5, "weekend"),
])
def test_time_gate(hhmm, wd, expected):
    h, m = map(int, hhmm.split(":"))
    now = datetime(2026, 10, 12 + wd, h, m, tzinfo=ET)
    assert cycle.time_gate(now, RULES) == expected


def test_fifo_pairs_partials_and_r():
    rows = [
        {"timestamp_iso": "2026-10-12T10:10:00-04:00", "symbol": "AAA", "side": "BUY", "size": "30", "fill_price": "100", "stop_price": "98"},
        {"timestamp_iso": "2026-10-12T10:40:00-04:00", "symbol": "AAA", "side": "SELL", "size": "10", "fill_price": "101.5"},
        {"timestamp_iso": "2026-10-12T15:52:00-04:00", "symbol": "AAA", "side": "SELL", "size": "20", "fill_price": "104"},
    ]
    closed = compute_perf.pair_trades(rows)
    assert [c["qty"] for c in closed] == [10, 20]
    assert closed[0]["R"] == pytest.approx(0.75) and closed[1]["R"] == pytest.approx(2.0)
    agg = compute_perf.aggregate(closed)
    assert agg["gross_pnl_usd"] == pytest.approx(95.0) and agg["profit_factor"] == "inf"
    html = compute_perf.render_html("2026-10-12", agg, closed, [{"symbol": "BBB", "qty": 5, "entry": 10, "stop": 9, "uR": 1.5}])
    assert "+1.50R" in html and 'http-equiv="refresh"' in html


def test_prefilter_screen_skips_stale_bars():
    days = pd.to_datetime(["2026-10-09", "2026-10-12"])
    prices = {"AAA": [10, 10.6], "BRK-B": [100, 101], "CCC": [2, 2.2]}  # +6%, +1%, < $3
    data = pd.concat({t: pd.DataFrame({"Open": p, "High": p, "Low": p, "Close": p}, index=days)
                      for t, p in prices.items()}, axis=1)
    res = morning_prefilter.screen(data, ["AAA", "BRK B", "CCC", "ZZZ"], 3.0, 3.0, TODAY)
    assert [s["ticker"] for s in res["survivors"]] == ["AAA"]
    assert res["below_gap"] == ["BRK B"] and res["below_price"] == ["CCC"] and res["failed"] == ["ZZZ"]
    stale = morning_prefilter.screen(data, ["AAA"], 3.0, 3.0, date(2026, 10, 13))
    assert stale["stale"] == ["AAA"]


def test_paper_live_guard(monkeypatch):
    monkeypatch.setenv("PAPER_TRADING", "true")
    monkeypatch.setenv("IBKR_PORT", "7496")
    assert common.check_paper_live_guard().startswith("ABORT")
    monkeypatch.setenv("IBKR_PORT", "4002")
    assert common.check_paper_live_guard() is None
    monkeypatch.setenv("PAPER_TRADING", "false")
    assert common.check_paper_live_guard().startswith("ABORT")


def test_sp500_list():
    from src.sp500_tickers import SP500_TICKERS
    assert 495 <= len(SP500_TICKERS) <= 510
    assert "BRK B" in SP500_TICKERS and "BRK-B" not in SP500_TICKERS
    assert SP500_TICKERS == sorted(SP500_TICKERS)
