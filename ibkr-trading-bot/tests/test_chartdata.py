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
