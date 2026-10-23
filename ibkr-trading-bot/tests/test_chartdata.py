from datetime import date, datetime, timedelta

import pandas as pd

from src import chartdata, common
from src.common import ET


def fake_bars(symbol, day):
    rows = []
    for d, base in ((day - timedelta(days=1), 99.0), (day, 100.0)):
        start = datetime(d.year, d.month, d.day, 8, 0, tzinfo=ET)
        for i in range(96):  # 08:00-16:00
            t = start + timedelta(minutes=5 * i)
            px = base + i * 0.05
            rows.append((t, px, px + 0.2, px - 0.2, px + 0.1, 1000 + i))
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t"), "5m"


def test_chart_has_candles_indicators_levels_and_markers(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "TRADES_PATH", tmp_path / "trades.csv")
    monkeypatch.setattr(chartdata, "SAFETY_LOG_PATH", tmp_path / "log.json")
    monkeypatch.setattr(chartdata, "_bars", fake_bars)
    monkeypatch.setattr(chartdata, "ticker_info", lambda s: {"longName": "Test Co"})
    day = date(2026, 10, 9)
    common.append_trade({"timestamp_iso": "2026-10-09T10:17:30-04:00", "symbol": "TST", "side": "BUY", "size": 10,
                         "fill_price": 101.5, "stop_price": 100.2, "strategy": "trend_join_long"})
    common.append_trade({"timestamp_iso": "2026-10-09T11:02:00-04:00", "symbol": "TST", "side": "SELL", "size": 10, "fill_price": 103})
    (tmp_path / "log.json").write_text('{"ts": "2026-10-09T10:17:20-04:00", "event": "evaluate", "symbol": "TST", "passed": true, "reasons": ["D1 ok"]}\n'
                                      '{"ts": "2026-10-09T10:12:00-04:00", "event": "evaluate", "symbol": "TST", "passed": false, "reasons": ["D1 FAIL"]}\n')
    d = chartdata.chart("TST", day)
    assert len(d["candles"]) == 96 and d["interval"] == "5m"
    assert {"EMA 9", "EMA 20", "EMA 50", "VWAP"} <= set(d["lines"])
    assert d["levels"]["Initial stop"] == 100.2 and "Premarket high" in d["levels"] and "Yesterday high" in d["levels"]
    buy, sell = d["markers"]
    # 10:17:30 fill snaps to the 10:15 bar; chart time is ET wall clock encoded as UTC
    assert buy["side"] == "BUY" and buy["time"] == int((pd.Timestamp("2026-10-09 10:15") - pd.Timestamp("1970-01-01")).total_seconds())
    assert sell["side"] == "SELL" and buy["at"] == "10:17:30"
    assert [r["event"] for r in d["reasons"]] == ["evaluate"] and d["reasons"][0]["passed"]  # failed checks left out
    assert d["info"]["longName"] == "Test Co"


def test_lab_markers_show_the_simulated_trade(tmp_path, monkeypatch):
    from datetime import date
    from src import chartdata, setup_lab
    monkeypatch.setattr(setup_lab, "RESULTS_PATH", tmp_path / "lab.json")
    setup_lab.save_results({"results": [{"id": "orb15", "name": "ORB", "sample": [
        {"symbol": "NVDA", "date": "2026-10-20", "time": "09:50", "side": "long", "entry": 100.0, "stop": 99.0,
         "R": 1.5, "exit": "stop (after breakeven/trail)", "exit_time": "11:05", "exit_price": 101.5},
        {"symbol": "AMD", "date": "2026-10-20", "time": "10:00", "side": "long", "entry": 1, "stop": 0.5, "R": 1, "exit": "x", "exit_time": "10:05"}]}]})
    marks, notes = chartdata.lab_markers("NVDA", date(2026, 10, 20), "orb15")
    assert [m["side"] for m in marks] == ["BUY", "SELL"] and marks[0]["stop"] == 99.0 and marks[1]["price"] == 101.5
    assert "simulated" in notes[0]["detail"] and chartdata.lab_markers("NVDA", date(2026, 10, 20), "nope") == ([], [])
