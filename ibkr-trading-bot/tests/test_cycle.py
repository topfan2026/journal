"""Drive cycle.py against a fake broker so order sequencing is tested without TWS."""
import os
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import cycle
from src import common, executor, marketdata
from src.common import ET
from tests.test_logic import RULES, TODAY, make_daily, make_intraday


class FakeIBKR:
    def __init__(self):
        self.held, self.prices, self.stops, self.calls, self.fill_list = {}, {}, {}, [], []
        self.next_id = 100
        self.ib = SimpleNamespace(fills=lambda: self.fill_list, sleep=lambda s: None)

    def _trade(self, oid):
        return SimpleNamespace(order=SimpleNamespace(orderId=oid, permId=oid + 9000))

    def place_stop(self, sym, qty, px):
        self.next_id += 1
        self.stops[self.next_id] = (sym, qty, round(px, 2))
        self.calls.append(("place_stop", sym, qty, round(px, 2)))
        return self._trade(self.next_id)

    def modify_stop(self, sym, oid, qty, px):
        if oid not in self.stops:
            return self.place_stop(sym, qty, px)
        self.stops[oid] = (sym, qty, round(px, 2))
        self.calls.append(("modify_stop", sym, qty, round(px, 2)))
        return self._trade(oid)

    def cancel(self, oid):
        self.calls.append(("cancel", oid))
        return self.stops.pop(oid, None) is not None

    def position_qty(self, sym):
        return self.held.get(sym, 0)

    def held_symbols(self):
        return {s for s, q in self.held.items() if q}

    def last_price(self, sym):
        return self.prices[sym]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("TRADES_PATH", "POSITIONS_PATH", "WATCHLIST_PATH", "SAFETY_LOG_PATH", "LOGS_DIR"):
        new = tmp_path / getattr(common, name).name
        monkeypatch.setattr(common, name, new)
        if hasattr(cycle, name):
            monkeypatch.setattr(cycle, name, new)
    monkeypatch.setattr(cycle, "now_et", lambda: datetime(2026, 10, 12, 11, 0, tzinfo=ET))
    monkeypatch.setattr(common, "now_et", lambda: datetime(2026, 10, 12, 11, 0, tzinfo=ET))
    monkeypatch.setattr(cycle, "safe_notify", lambda *a, **k: None)
    from src import strategies
    monkeypatch.setattr(strategies, "STORE", tmp_path / "strategies.json")
    fake = FakeIBKR()
    trades = []

    def run_trade(sym, side, size, stop_price=None, timeout=30, strategy=""):
        trades.append((side, sym, size))
        fill = fake.prices[sym]
        fake.held[sym] = fake.held.get(sym, 0) + (size if side == "BUY" else -size)
        common.append_trade({"timestamp_iso": "2026-10-12T11:00:00-04:00", "symbol": sym, "side": side,
                             "size": size, "fill_price": fill, "order_id": 1, "status": "Filled", "stop_price": stop_price or "",
                             "strategy": strategy})
        return {"status": "Filled", "filled": size, "fill_price": fill}, ""

    monkeypatch.setattr(executor, "run_trade", run_trade)
    return SimpleNamespace(fake=fake, trades=trades, tmp=tmp_path)


def pos(sym="AAA", entry=100.0, stop=98.0, qty=30, state="pre_breakeven", partial=False, oid=None):
    return {"symbol": sym, "entry_price": entry, "entry_time_iso": "2026-10-12T10:10:00-04:00", "qty": qty,
            "initial_stop": stop, "stop": stop, "stop_order_id": oid, "stop_perm_id": None,
            "state": state, "partial_done": partial, "R": entry - stop}


def flat_bars(monkeypatch, lows=None):
    idx = pd.date_range("2026-10-12 10:00", periods=len(lows or [1]), freq="5min", tz=ET)
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": lows or [1.0], "Close": 1.0, "Volume": 1}, index=idx)
    monkeypatch.setattr(marketdata, "intraday_bars", lambda s, period="1d": df)


def test_jump_past_1r_takes_partial_then_breakeven(env, monkeypatch):
    f = env.fake
    t = f.place_stop("AAA", 30, 98.0)
    f.held["AAA"], f.prices["AAA"] = 30, 102.5  # +1.25R
    flat_bars(monkeypatch)
    p = [pos(oid=t.order.orderId)]
    cycle.manage(f, p, RULES)
    assert env.trades == [("SELL", "AAA", 10)]
    # stop shrunk to 20 BEFORE the sell, tightened to entry-1% after the partial, then breakeven
    assert f.calls[1:] == [("modify_stop", "AAA", 20, 98.0), ("modify_stop", "AAA", 20, 99.0),
                           ("modify_stop", "AAA", 20, 100.0)]
    assert p[0]["qty"] == 20 and p[0]["partial_done"] and p[0]["state"] == "post_breakeven"


def test_trail_ratchets_up_only(env, monkeypatch):
    f = env.fake
    t = f.place_stop("AAA", 20, 100.0)
    f.held["AAA"], f.prices["AAA"] = 20, 105.0
    flat_bars(monkeypatch, lows=[104, 103, 102, 103, 104, 104.5])  # swing low 102 at 10:10
    p = [pos(stop=98.0, qty=20, state="post_breakeven", partial=True, oid=t.order.orderId)]
    p[0]["stop"] = 100.0
    cycle.manage(f, p, RULES)
    assert p[0]["stop"] == 101.99
    flat_bars(monkeypatch, lows=[104, 103, 99, 103, 104, 104.5])  # lower swing low: no change
    cycle.manage(f, p, RULES)
    assert p[0]["stop"] == 101.99


def test_stop_out_matched_by_order_id_not_qty(env):
    f = env.fake
    t = f.place_stop("AAA", 20, 100.0)
    p = pos(qty=20, oid=t.order.orderId)
    # A 20-share SELL fill from a DIFFERENT order must not count as a stop-out.
    other = SimpleNamespace(contract=SimpleNamespace(symbol="AAA"), time=None,
                            execution=SimpleNamespace(side="SLD", orderId=999, permId=1, shares=20, price=99.0))
    f.fill_list.append(other)
    f.held["AAA"] = 20
    assert cycle.reconcile(f, [p]) == [p]
    stop_fill = SimpleNamespace(contract=SimpleNamespace(symbol="AAA"), time=None,
                                execution=SimpleNamespace(side="SLD", orderId=t.order.orderId, permId=0, shares=20, price=99.9))
    f.fill_list.append(stop_fill)
    f.held["AAA"] = 0
    assert cycle.reconcile(f, [p]) == []
    last = common.read_trades()[-1]
    assert last["side"] == "SELL" and last["status"] == "StopFilled" and last["size"] == "20"


def test_entry_scan_buys_and_protects(env, monkeypatch):
    f = env.fake
    common.WATCHLIST_PATH.write_text("# header\nAAA  # gap\nHELD\n")
    f.held["HELD"] = 5
    intra = make_intraday()
    price = float(intra["High"].iloc[:-1].max()) + 0.5
    f.prices.update(AAA=price, HELD=50.0)
    monkeypatch.setattr(marketdata, "daily_bars", lambda s, period="1y": make_daily())
    monkeypatch.setattr(marketdata, "intraday_bars", lambda s, period="30d": intra)
    monkeypatch.setattr(cycle, "now_et", lambda: datetime(TODAY.year, TODAY.month, TODAY.day, 11, 0, tzinfo=ET))
    stamp = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 55, tzinfo=ET).timestamp()
    os.utime(common.WATCHLIST_PATH, (stamp, stamp))
    positions = []
    cycle.entry_scan(f, positions, RULES)
    assert [t[1] for t in env.trades] == ["AAA"]  # HELD skipped
    p = positions[0]
    assert p["stop"] == pytest.approx(103.0 * 0.99)
    assert f.stops[p["stop_order_id"]] == ("AAA", p["qty"], round(103.0 * 0.99, 2))
    assert p["qty"] * price <= 2500


def test_force_close_flattens_and_cancels(env, monkeypatch):
    f = env.fake
    t = f.place_stop("AAA", 20, 100.0)
    f.held["AAA"], f.prices["AAA"] = 20, 103.0
    left = cycle.force_close(f, [pos(qty=20, oid=t.order.orderId)])
    assert left == [] and ("cancel", t.order.orderId) in f.calls and env.trades == [("SELL", "AAA", 20)]


def _strategies(tmp_path, items):
    from src import strategies
    strategies.save(items)
    return strategies


def test_custom_strategy_buys_with_its_own_tag_exits_and_cap(env, monkeypatch):
    from src import strategies as st
    f = env.fake
    f.prices.update(AAA=50.0, BBB=60.0, CCC=70.0)
    orb = {"id": "orb_1", "type": "orb", "name": "My ORB", "enabled": True,
           "params": {**st.defaults_for("orb"), "universe": "custom", "tickers": "AAA,BBB,CCC",
                      "max_trades_per_day": 2, "take_profit_R": 2.0, "earliest_entry_et": "09:45", "latest_entry_et": "11:30"}}
    st.save([{"id": st.TREND_JOIN_ID, "type": "trend_join", "name": "Trend Join Long", "enabled": False}, orb])
    monkeypatch.setattr(marketdata, "daily_bars", lambda s, period="1y": make_daily())
    monkeypatch.setattr(marketdata, "intraday_bars", lambda s, period="30d": make_intraday())
    monkeypatch.setattr(st, "evaluate", lambda cfg, d, i, price, today, rules, t: {"pass": True, "reasons": [], "metrics": {"stop": price - 1}})
    positions = []
    cycle.entry_scan(f, positions, RULES)  # 11:00 ET in the fixture: inside ORB's window
    assert [p["symbol"] for p in positions] == ["AAA", "BBB"]  # per-strategy cap of 2
    assert all(p["strategy"] == "orb_1" and p["exit"]["take_profit_R"] == 2.0 for p in positions)
    assert {r["strategy"] for r in common.read_trades()} == {"orb_1"}


def test_strategy_outside_its_window_does_nothing(env, monkeypatch):
    from src import strategies as st
    orb = {"id": "orb_1", "type": "orb", "enabled": True,
           "params": {**st.defaults_for("orb"), "universe": "custom", "tickers": "AAA", "latest_entry_et": "10:30"}}
    st.save([{"id": st.TREND_JOIN_ID, "type": "trend_join", "enabled": False}, orb])
    monkeypatch.setattr(st, "evaluate", lambda *a: pytest.fail("should not evaluate outside the window"))
    cycle.entry_scan(env.fake, [], RULES)  # fixture time is 11:00 ET


def test_take_profit_sells_everything(env, monkeypatch):
    f = env.fake
    t = f.place_stop("AAA", 30, 98.0)
    f.held["AAA"], f.prices["AAA"] = 30, 104.5  # +2.25R with R = 2
    flat_bars(monkeypatch)
    p = pos(oid=t.order.orderId)
    p.update(strategy="orb_1", exit={"partial_profit_trigger_R": 999, "partial_profit_fraction": .5,
                                     "breakeven_trigger_R": 999, "take_profit_R": 2.0, "trail": True})
    positions = [p]
    cycle.manage(f, positions, RULES)
    assert env.trades == [("SELL", "AAA", 30)] and positions == []
    assert ("cancel", t.order.orderId) in f.calls


def test_old_trades_csv_is_migrated(env):
    common.TRADES_PATH.write_text("timestamp_iso,symbol,side,size,fill_price,order_id,status,stop_price\n"
                                  "2026-10-12T10:10:00-04:00,AAA,BUY,10,100,1,Filled,98\n")
    rows = common.read_trades()
    assert rows[0]["symbol"] == "AAA" and rows[0]["strategy"] == ""
    common.append_trade({"timestamp_iso": "2026-10-12T11:00:00-04:00", "symbol": "AAA", "side": "SELL", "size": 10,
                         "fill_price": 101, "strategy": "trend_join_long"})
    assert [r["strategy"] for r in common.read_trades()] == ["", "trend_join_long"]
    assert common.todays_buy_count(strategy="trend_join_long") == 1  # untagged old BUY counts as Trend Join
