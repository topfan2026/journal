from datetime import time

import pytest

from src import builder
from src import strategies as st
from tests.test_logic import RULES, TODAY, make_daily
from tests.test_strategies import PRE, cfg, one_min


def C(a, op, b, an=0, bn=0, x=1):
    return {"a": a, "an": an, "op": op, "b": b, "bn": bn, "x": x}


RTH = [(100.2, 100.6, 100.0, 100.5), (100.5, 100.9, 100.4, 100.8),
       (100.8, 101.4, 100.7, 101.3),   # 9:32 closes above the 101 premarket high
       (101.3, 101.5, 101.2, 101.4)]   # 9:33 still forming


def run(conds, price=101.4, now=time(9, 33, 20), **params):
    bars = one_min(PRE, RTH)
    c = cfg("custom", **{"timeframe": "1m", "conditions": conds, "min_stop_pct": 0, **params})
    return st.evaluate(c, make_daily(), bars, price, TODAY, RULES, now, bars_1m=bars)


def test_custom_long_on_a_cross_with_stop_under_the_signal_candle():
    res = run([C("close", "crosses_above", "pm_high")])
    assert res["pass"], res["reasons"]
    assert res["metrics"]["side"] == "long" and res["metrics"]["stop"] == pytest.approx(100.69)
    assert res["metrics"]["signal_time"] == "09:32"
    assert any("Candle close crosses above Premarket high (101.30 vs 101.00)" in r for r in res["reasons"])


def test_all_conditions_must_hold_and_values_are_explained():
    res = run([C("close", "crosses_above", "pm_high"), C("close", ">", "number", bn=200)])
    assert not res["pass"] and any(r.startswith("if FAIL: Candle close is above 200") for r in res["reasons"])


def test_only_new_signals_and_stale_data_is_skipped():
    # "close above 100" was already true on the candle before -> not a new signal
    res = run([C("close", ">", "number", bn=100)])
    assert not res["pass"] and "not a new signal" in " ".join(res["reasons"])
    assert run([C("close", ">", "number", bn=100)], fresh_only=False)["pass"]
    late = run([C("close", "crosses_above", "pm_high")], now=time(9, 36, 0))  # data stops at 9:33
    assert not late["pass"] and "data is behind" in " ".join(late["reasons"])


def test_custom_short_and_stop_choices():
    res = run([C("close", "crosses_above", "pm_high")], side="short", price=100.5)
    assert res["metrics"]["side"] == "short" and res["metrics"]["stop"] == pytest.approx(101.41)  # signal high + 1c
    assert run([C("close", "crosses_above", "pm_high")], stop_rule="day")["metrics"]["stop"] == pytest.approx(99.99)
    assert run([C("close", "crosses_above", "pm_high")], stop_rule="pct", stop_n=1)["metrics"]["stop"] == pytest.approx(100.39)
    assert run([C("close", "crosses_above", "pm_high")], stop_rule="n_bars", stop_n=2)["metrics"]["stop"] == pytest.approx(100.39)
    wide = run([C("close", "crosses_above", "pm_high")], min_stop_pct=1.5)
    assert wide["metrics"]["stop"] == pytest.approx(99.88) and wide["metrics"]["stop_widened_from"] == pytest.approx(100.69)


def test_building_blocks_compute():
    bars = one_min(PRE, RTH)
    from src.filters import _rth
    rthc = _rth(bars).iloc[:-1]
    day_all = bars[bars.index.date == TODAY]
    s = lambda k, n=0: builder._series(k, n, rthc, TODAY, day_all, make_daily().iloc[:-1])
    assert s("pm_high").iloc[-1] == 101.0 and s("pm_low").iloc[-1] == 99.0
    assert s("today_open").iloc[-1] == 100.2 and s("day_high").iloc[-1] == 100.9  # before the 9:32 candle
    assert s("prev_close").iloc[-1] == 100.8 and s("number", 5).iloc[-1] == 5
    assert s("or_high", 2).iloc[-1] == 100.9 and s("or_high", 2).isna().iloc[0]  # range not finished at 9:30
    assert s("vwap").iloc[-1] == pytest.approx(100.733, abs=0.001)
    for k in builder.OPERANDS:
        s(k, builder.OPERANDS[k][2] or 3)  # every block computes without error


def test_conditions_are_validated_on_save():
    raw = '[{"a":"ema","an":"9.6","op":">","b":"sma","bn":-4,"x":"2"},{"a":"bad","op":">","b":"close"},{"a":"close","op":"??","b":"vwap"}]'
    assert builder.clean_conditions(raw) == [{"a": "ema", "an": 10, "op": ">", "b": "sma", "bn": 1, "x": 2.0}]
    assert st.coerce("custom", {"conditions": raw})["conditions"][0]["b"] == "sma"
    assert "custom" in st.TEMPLATES and st.defaults_for("custom")["conditions"] == builder.DEFAULT_CONDITIONS
    assert run([])["reasons"][-1].startswith("conditions FAIL")
