"""AI paper trader: strategy rules, day limits, and the trade lifecycle against a fake broker."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import paper_trader as pt
import trading_rules as tr

ET = ZoneInfo("America/New_York")


def bars_from(closes, vols=None, spread=0.05):
    vols = vols or [1000] * len(closes)
    out, prev = [], closes[0]
    for i, (c, v) in enumerate(zip(closes, vols)):
        out.append(tr.Bar(str(i), prev, max(prev, c) + spread, min(prev, c) - spread, c, v))
        prev = c
    return out


def test_orb_breakout_fires_once_on_the_breakout_bar():
    closes = [10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6]   # range high 10.35 (10.3 + spread)
    vols = [1000] * 6 + [3000]
    bars = bars_from(closes, vols)
    sig = tr.orb_signal("ABC", bars, orb_min=5)
    assert sig and sig.strategy == "ORB" and sig.entry == 10.6
    assert sig.stop < sig.entry < sig.target
    assert abs((sig.target - sig.entry) - 2 * (sig.entry - sig.stop)) < 0.02
    assert tr.orb_signal("ABC", bars_from(closes + [10.7], vols + [3000]), orb_min=5) is None  # not again


def test_orb_needs_volume():
    closes = [10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6]
    assert tr.orb_signal("ABC", bars_from(closes), orb_min=5) is None  # breakout on ordinary volume


def test_vwap_reclaim():
    closes = [10.0, 10.4, 10.3, 9.9, 9.8, 9.85, 9.9, 10.35]
    vols = [2000, 2000, 2000, 1000, 1000, 1000, 1000, 4000]
    sig = tr.vwap_reclaim_signal("XYZ", bars_from(closes, vols))
    assert sig and sig.strategy == "VWAP reclaim" and sig.stop < sig.entry


def test_position_size_respects_risk_and_cap():
    assert tr.position_size(10.0, 9.5, risk_usd=100, max_value=10000) == 200
    assert tr.position_size(100.0, 99.9, risk_usd=100, max_value=10000) == 100  # capped by $10k
    assert tr.position_size(10.0, 10.0, risk_usd=100, max_value=10000) == 0


def test_day_limits():
    book = tr.DayBook(max_trades=5, max_losses=3)
    for _ in range(3):
        book.trades.append({"symbol": "A", "pnl": -50})
    ok, why = book.can_trade()
    assert not ok and "3 losses" in why
    book = tr.DayBook(max_trades=5, max_losses=3, trades=[{"symbol": s, "pnl": 10} for s in "ABCDE"])
    assert not book.can_trade()[0]


class FakeBroker:
    def __init__(self, bars):
        self._bars, self.orders, self.cancelled = bars, [], 0
        self.fill, self.exit = False, None

    def connect(self): return ["DU123"]
    def connected(self): return True
    def sleep(self, s): pass
    def scan(self, rows): return ["ABC"]
    def bars(self, symbol): return self._bars
    def last_price(self, symbol): return self._bars[-1].close
    def place_bracket(self, symbol, qty, limit, target, stop):
        self.orders.append((symbol, qty, limit, target, stop))
        return {"id": len(self.orders)}
    def status(self, h):
        return {"filled": self.fill, "fill": 10.6 if self.fill else None, "dead": False,
                "exit": self.exit, "exit_price": None}
    def cancel(self, h): self.cancelled += 1
    def flatten(self, symbol, h, qty): return 10.7
    def disconnect(self): pass


def test_trader_lifecycle_paper(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_RISK_USD", "100")
    monkeypatch.setenv("TRADER_STRATEGIES", "orb")
    closes = [10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6]
    broker = FakeBroker(bars_from(closes, [1000] * 6 + [3000]))
    now = datetime(2026, 10, 5, 9, 45, tzinfo=ET)  # Monday, after the opening range
    t = pt.Trader(tmp_path, broker, clock=lambda: now)
    t.step(now)
    assert broker.orders and broker.orders[0][0] == "ABC"     # bracket order sent
    assert t.open and t.phase == "in a trade"
    broker.fill = True
    t.step(now)
    assert t.open["fill"] == 10.6
    broker.exit = "target"
    t.step(now)
    assert t.open is None and t.book.trades[-1]["result"] == "win" and t.book.pnl > 0
    state = (tmp_path / "trader.json").read_text()
    assert "ABC" in state and '"wins": 1' in state
    t.step(now)                                              # ABC already traded today: no new order
    assert len(broker.orders) == 1


def test_trader_watch_only_and_weekend(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_STRATEGIES", "orb")
    closes = [10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6]
    broker = FakeBroker(bars_from(closes, [1000] * 6 + [3000]))
    now = datetime(2026, 10, 5, 9, 45, tzinfo=ET)
    t = pt.Trader(tmp_path, broker, watch_only=True, clock=lambda: now)
    t.step(now)
    assert not broker.orders and "watch only" in t.captions[-1]["text"]
    sat = datetime(2026, 10, 3, 9, 45, tzinfo=ET)
    t2 = pt.Trader(tmp_path / "w", FakeBroker([]), clock=lambda: sat)
    t2.step(sat)
    assert t2.phase == "closed"


def test_trader_stops_after_three_losses(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_STRATEGIES", "orb")
    broker = FakeBroker(bars_from([10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6], [1000] * 6 + [3000]))
    now = datetime(2026, 10, 5, 10, 0, tzinfo=ET)
    t = pt.Trader(tmp_path, broker, clock=lambda: now)
    t.book.trades = [{"symbol": s, "pnl": -100} for s in ("X", "Y", "Z")]
    t.step(now)
    assert not broker.orders and t.phase == "done for the day"


def test_flatten_on_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_STRATEGIES", "orb")
    broker = FakeBroker(bars_from([10.0, 10.2, 10.1, 10.3, 10.2, 10.25, 10.6], [1000] * 6 + [3000]))
    now = datetime(2026, 10, 5, 9, 45, tzinfo=ET)
    t = pt.Trader(tmp_path, broker, clock=lambda: now)
    t.step(now)
    broker.fill = True
    t.step(now)
    t.close_out()
    assert t.open is None and t.book.trades[-1]["how"] == "flatten"


def test_overlay_server_serves_state(tmp_path):
    import json, urllib.request
    (tmp_path / "trader.json").write_text(json.dumps({"phase": "hunting"}))
    assert pt.serve_overlay(tmp_path, port=47681)
    body = urllib.request.urlopen("http://127.0.0.1:47681/state").read()
    assert json.loads(body)["phase"] == "hunting"
    assert b"AI PAPER TRADER" in urllib.request.urlopen("http://127.0.0.1:47681/").read()
