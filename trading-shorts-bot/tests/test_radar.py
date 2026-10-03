import json
from datetime import datetime

import market_radar as mr


def series(start, step, n=300):
    return [start + step * i for i in range(n)]


def sample():
    return {"closes": {"SPY": series(400, 0.5), "^VIX": [15 + (i % 7) * 0.3 for i in range(300)],
                       "^VIX3M": [18.0] * 300, "^SKEW": [145.0] * 300, "IWM": series(200, 0.05),
                       "LQD": series(105, 0.01), "HYG": series(76, 0.01), "IEF": series(95, 0.0),
                       "SMH": series(200, 0.6)},
            "fred": {"DGS2": 3.9, "DGS10": 4.3, "DFF": 3.6}, "watch": {"NVDA": series(100, 0.3)}}


def test_metrics_and_report():
    m = mr.metrics(sample())
    assert m["spy_ma"] > 0 and 0 <= m["rsi"] <= 100
    assert abs(m["liq"] - 0.3) < 1e-9 and abs(m["yc"] - 0.4) < 1e-9
    assert "vix_roc_5d" in m and m["vix_term"] < 1
    text = mr.report(m, datetime(2026, 10, 2, 17, 23).astimezone())
    assert "SPY vs 200-MA" in text and "Systemic:" in text and "Semi breadth" in text
    assert "Watchlist" in text and "NVDA" in text and "not financial advice" in text


def test_rsi_extremes():
    assert mr.rsi(series(100, 1, 40)) == 100.0
    assert mr.rsi(series(100, -1, 40)) < 1


def test_missing_data_does_not_break_report():
    data = sample()
    data["closes"]["^SKEW"] = None
    data["fred"]["DFF"] = None
    text = mr.report(mr.metrics(data))
    assert "SKEW n/a" in text


def test_signals():
    m = {"spy_ma": -2.0, "vix_z": 2.5, "vix_term": 1.1, "yc": -0.2}
    s = mr.signals(m)
    assert len(s) == 4


def test_due(monkeypatch):
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_TIMES", "06:00,13:15")
    monkeypatch.setenv("RADAR_DAYS", "mon-fri")
    mon = datetime(2026, 10, 5, 6, 3)
    assert mr.due(mon, set()) == "2026-10-05 06:00"
    assert mr.due(mon, {"2026-10-05 06:00"}) is None
    assert mr.due(datetime(2026, 10, 5, 6, 20), set()) is None      # too late for that slot
    assert mr.due(datetime(2026, 10, 3, 6, 3), set()) is None       # Saturday
    monkeypatch.setenv("RADAR_ENABLED", "false")
    assert mr.due(mon, set()) is None


def test_telegram_send(monkeypatch):
    sent = {}

    class Resp:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=0):
        sent["url"], sent["data"] = req.full_url, req.data
        return Resp(json.dumps({"ok": True}).encode())
    monkeypatch.setattr(mr.urllib.request, "urlopen", fake_urlopen)
    mr.telegram_send("hello", token="T", chat_id="42")
    assert sent["url"].endswith("/botT/sendMessage") and b"chat_id=42" in sent["data"]


def test_regime_and_tightening_context():
    m = {"spy_ma": 6.4, "vix_z": -0.85, "liq": 1.18, "breadth": -1.0}
    assert mr.regime(m).startswith("🟢 SAFE")
    assert "2000/2022" in mr.summary(m)
    assert mr.regime({"spy_ma": -1.0}).startswith("🔴")
