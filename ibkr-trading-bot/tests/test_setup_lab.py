from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from src import setup_lab as lab
from src import strategies as st
from src.common import ET
from tests.test_logic import RULES


def market(seed=1, n_days=8, start=date(2026, 9, 28)):
    """Random-walk 1-minute bars (premarket 8:00-9:29 + regular hours) for n weekdays, plus 5-minute and daily bars."""
    rng = np.random.default_rng(seed)
    rows, px, d, days = [], 100.0, start, 0
    while days < n_days:
        if d.weekday() < 5:
            t = datetime(d.year, d.month, d.day, 8, 0, tzinfo=ET)
            while t.time() < time(16, 0):
                o = px
                c = max(1.0, o * (1 + rng.normal(0, 0.0015)))
                h, l = max(o, c) * (1 + abs(rng.normal(0, 0.0005))), min(o, c) * (1 - abs(rng.normal(0, 0.0005)))
                vol = int(rng.integers(1000, 5000) * (0.2 if t.time() < time(9, 30) else 1))
                rows.append((t, o, h, l, c, vol))
                px = c
                t += timedelta(minutes=1)
            days += 1
        d += timedelta(days=1)
    one = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")
    five = one.resample("5min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    hist = pd.date_range(end=pd.Timestamp(start) - pd.Timedelta(days=1), periods=260, freq="B")
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(hist)))
    daily = pd.DataFrame({"Open": closes, "High": closes * 1.01, "Low": closes * 0.99, "Close": closes, "Volume": 1e6}, index=hist)
    rth_days = sorted({x for x in five.index.date})
    for dd in rth_days:  # the replayed days themselves, from the intraday data
        day = five[(five.index.date == dd) & (five.index.time >= time(9, 30))]
        daily.loc[pd.Timestamp(dd)] = [day.Open.iloc[0], day.High.max(), day.Low.min(), day.Close.iloc[-1], day.Volume.sum()]
    return daily.sort_index(), five, one


def cfg_exit(**kw):
    ex = {"partial_profit_trigger_R": 1.0, "partial_profit_fraction": 0.5, "breakeven_trigger_R": 1.0, "take_profit_R": 0, "trail": False}
    ex.update(kw)
    return {"exit": ex}


def bars(rows, day=date(2026, 10, 1), start=time(10, 0)):
    t0 = datetime.combine(day, start).replace(tzinfo=ET)
    return pd.DataFrame([(t0 + timedelta(minutes=5 * i), *r, 1000) for i, r in enumerate(rows)],
                        columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


def test_exit_partial_then_breakeven_stop():
    path = bars([(100, 100.5, 99.8, 100.4), (100.4, 101.2, 100.3, 101.0), (101.0, 101.1, 99.9, 100.0)])
    r, why, at, _ = lab._exit(cfg_exit(), 1, 100.0, 99.0, path, path, 5, path.index[0])
    assert r == pytest.approx(0.5 - 0.5 * 100 * lab.SLIP_PCT / 100, abs=1e-6)  # +1R on half, ~0 on the rest
    assert "after breakeven" in why and at == "10:10"


def test_exit_stop_counts_before_target_in_the_same_candle_and_gaps_fill_worse():
    path = bars([(100, 103, 98.5, 102)])
    r, why, _, _ = lab._exit(cfg_exit(take_profit_R=2), 1, 100.0, 99.0, path, path, 5, path.index[0])
    assert why == "stop" and r < -1  # stop first (conservative) plus slippage
    gap = bars([(100, 100.2, 99.5, 99.8), (98.0, 98.2, 97.5, 98.0)])
    r, _, _, px = lab._exit(cfg_exit(), 1, 100.0, 99.0, gap, gap, 5, gap.index[0])
    assert r == pytest.approx(-2.0 - 100 * lab.SLIP_PCT / 100, abs=1e-6)  # filled at the gap open, not the stop
    assert px == pytest.approx(98.0 - 100 * lab.SLIP_PCT / 100)


def test_short_target_and_end_of_day():
    path = bars([(100, 100.2, 98.9, 99.0), (99.0, 99.1, 97.9, 98.0)])
    r, why, _, _ = lab._exit(cfg_exit(take_profit_R=2, partial_profit_trigger_R=999, breakeven_trigger_R=999), -1, 100.0, 101.0, path, path, 5, path.index[0])
    assert why == "target" and r == pytest.approx(2.0)
    late = bars([(100, 100.2, 99.9, 100.1), (99.0, 99.5, 98.8, 99.2)], start=time(15, 46))
    r, why, _, _ = lab._exit(cfg_exit(partial_profit_trigger_R=999, breakeven_trigger_R=999), -1, 100.0, 101.0, late, late, 5, late.index[0])
    assert why == "end of day" and r == pytest.approx(1.0)  # covered at the 15:51 candle's open
    five = bars([(100, 100.2, 99.9, 100.1), (99.5, 99.6, 99.4, 99.5)], start=time(15, 45))
    r, why, at, px = lab._exit(cfg_exit(partial_profit_trigger_R=999, breakeven_trigger_R=999), -1, 100.0, 101.0, five, five, 5, five.index[0])
    assert (why, at, px) == ("end of day", "15:50", 99.5)  # the 15:50 candle holds 15:51: covered there, not at 15:55


def test_no_look_ahead_entry_is_the_open_after_the_signal_candle():
    daily, five, one = market()
    d = sorted({x for x in five.index.date})[-1]
    rth = five[(five.index.date == d) & (five.index.time >= time(9, 30))]
    level = float(rth["Close"].iloc[5]) - 0.0001  # make sure some candle closes above it
    s = {"id": "t", "type": "custom", "params": {**st.defaults_for("custom"), "universe": "custom", "tickers": "X",
         "earliest_entry_et": "09:35", "latest_entry_et": "15:00", "min_stop_pct": 0, "fresh_only": False,
         "conditions": [{"a": "close", "an": 0, "op": ">", "b": "number", "bn": level, "x": 1}]}}
    cfg = st.config(s, RULES)
    trades = lab.backtest_symbol(cfg, "X", daily, five, one, [d], RULES)
    assert trades
    t0 = trades[0]
    entry_bar = rth.loc[rth.index.strftime("%H:%M") == t0["time"]].iloc[0]
    prev = rth[rth.index < rth.index[rth.index.strftime("%H:%M") == t0["time"]][0]].iloc[-1]
    assert prev["Close"] > level  # the signal came from a COMPLETED candle
    assert t0["entry"] == pytest.approx(entry_bar["Open"] * (1 + lab.SLIP_PCT / 100), abs=0.01)  # filled at the next open
    assert t0["stop"] == pytest.approx(round(prev["Low"] - 0.01, 2))


def test_every_playbook_setup_and_user_strategy_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STORE", tmp_path / "strategies.json")
    data = {s: market(seed=i + 2) for i, s in enumerate(["AAA", "BBB"])}
    seen = []
    res = lab.run(["AAA", "BBB"], 5, RULES, lambda s: data[s], include_mine=True, report=lambda *a: seen.append(a))
    assert not res["errors"], res["errors"]
    names = [r["name"] for r in res["results"]]
    assert {p["name"] for p in lab.PLAYBOOK} <= set(names) and "Trend Join Long" in names
    scores = [r["score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True) and seen
    for r in res["results"]:
        assert r["verdict"] in {"Strong", "Promising", "Weak", "Not enough trades", "No trades"}
        for t in r["sample"]:
            assert (t["entry"] - t["stop"]) * (1 if t["side"] == "long" else -1) > 0


def test_stats_and_verdicts():
    days = [date(2026, 10, i) for i in range(1, 22)]
    good = [{"symbol": "A", "date": days[i % 21].isoformat(), "time": "10:00", "R": 1.5 if i % 2 else -1} for i in range(30)]
    s = lab.stats(good, days)
    assert s["trades"] == 30 and s["win_rate"] == pytest.approx(50) and s["avg_R"] == pytest.approx(0.25)
    assert s["profit_factor"] == pytest.approx(1.5) and s["verdict"] == "Strong" and s["curve"][-1] == pytest.approx(7.5)
    assert lab.stats(good[:5], days)["verdict"] == "Not enough trades"
    bad = [{**t, "R": -t["R"]} for t in good]
    assert lab.stats(bad, days)["verdict"] == "Weak" and lab.stats([], days)["verdict"] == "No trades"


def test_speed_up_gate_gives_exactly_the_same_trades(monkeypatch):
    daily, five, one = market(seed=7)
    days = sorted({x for x in five.index.date})[-4:]
    for c in lab.candidates(RULES, ["X"], include_mine=False):
        if c["kind"] not in ("custom", "pm_break"):
            continue
        cfg = {**c["cfg"], "params": {**c["cfg"]["params"], "fresh_only": False}} if c["kind"] == "custom" else c["cfg"]
        for cf in (c["cfg"], cfg):
            fast = lab.backtest_symbol(cf, "X", daily, five, one, days, RULES)
            with monkeypatch.context() as mp:
                mp.setattr(lab, "_gate", lambda *a, **k: None)
                slow = lab.backtest_symbol(cf, "X", daily, five, one, days, RULES)
            assert fast == slow, c["name"]


def test_parallel_run_matches_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STORE", tmp_path / "strategies.json")
    data = {s: market(seed=i + 11, n_days=4) for i, s in enumerate(["AAA", "BBB"])}
    one = lab.run(["AAA", "BBB"], 2, RULES, lambda s: data[s], include_mine=False)
    two = lab.run(["AAA", "BBB"], 2, RULES, lambda s: data[s], include_mine=False, workers=2)
    strip = lambda r: [(x["id"], x["trades"], round(x["total_R"], 6)) for x in r["results"]]
    assert strip(one) == strip(two) and not two["errors"]
