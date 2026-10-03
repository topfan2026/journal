"""AI paper trader for the live show: trades scanner movers on the PAPER account and narrates.

    python paper_trader.py run            trade (paper account only)
    python paper_trader.py run --watch    signals and commentary only, no orders
    python paper_trader.py overlay        just serve the OBS overlay (to position it in OBS)

The live show starts it when TRADER_ENABLED=true and stops it at the end (it closes any open
paper position first). Rules live in trading_rules.py; the day's limits (TRADER_MAX_TRADES,
TRADER_MAX_LOSSES) are enforced here, in code, whatever the strategy says.

State for the overlay and the app: Live/trader.json. Trade journal: Live/<date>/trades.json.
Overlay for OBS (browser source): http://127.0.0.1:47622/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import ConfigError, Settings, env, env_bool, env_float
import trading_rules as tr

log = logging.getLogger("trader")
BOT_DIR = Path(__file__).resolve().parent
OVERLAY_FILE = BOT_DIR / "overlay.html"


def eastern():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def et_time(value: str, day: datetime) -> datetime:
    h, m = (int(x) for x in value.split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def strategies() -> list[str]:
    raw = (env("TRADER_STRATEGIES", "orb,vwap") or "orb,vwap").lower()
    return [s.strip() for s in raw.split(",") if s.strip() in tr.STRATEGIES]


# --------------------------------------------------------------------------- broker (IB Gateway)

class IBBroker:
    """The only part that talks to IB Gateway; everything else is testable without it."""

    def __init__(self, readonly: bool):
        self.readonly = readonly
        self.ib = None
        self.contracts: dict = {}
        self.subs: dict = {}

    def connect(self) -> list[str]:
        import ibkr
        from ib_async import IB
        self.ib = IB()
        self.ib.connect(ibkr.host(), ibkr.port(), clientId=int(env_float("TRADER_CLIENT_ID", 31)),
                        readonly=self.readonly, timeout=env_float("IB_CONNECT_TIMEOUT", 20))
        accounts = self.ib.managedAccounts()
        ibkr.check_paper(accounts)  # never trades a live account
        return accounts

    def connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()

    def sleep(self, seconds: float) -> None:
        self.ib.sleep(seconds)

    def scan(self, rows: int) -> list[str]:
        from ib_async import ScannerSubscription
        sub = ScannerSubscription(
            instrument="STK", locationCode="STK.US.MAJOR",
            scanCode=env("TRADER_SCAN", "TOP_PERC_GAIN") or "TOP_PERC_GAIN", numberOfRows=rows,
            abovePrice=env_float("TRADER_MIN_PRICE", 2), belowPrice=env_float("TRADER_MAX_PRICE", 200),
            aboveVolume=int(env_float("TRADER_MIN_VOLUME", 200000)))
        data = self.ib.reqScannerData(sub)
        return [d.contractDetails.contract.symbol for d in data
                if d.contractDetails.contract.secType == "STK"]

    def _contract(self, symbol: str):
        if symbol not in self.contracts:
            from ib_async import Stock
            c = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(c)
            self.contracts[symbol] = c
        return self.contracts[symbol]

    def bars(self, symbol: str) -> list[tr.Bar]:
        """Today's regular-hours 1-minute bars, CLOSED ones only (the last bar is still forming)."""
        if symbol not in self.subs:
            self.subs[symbol] = self.ib.reqHistoricalData(
                self._contract(symbol), "", "1 D", "1 min", "TRADES", useRTH=True, keepUpToDate=True)
        raw = list(self.subs[symbol])[:-1]
        return [tr.Bar(str(b.date), b.open, b.high, b.low, b.close, b.volume) for b in raw]

    def last_price(self, symbol: str) -> float | None:
        sub = self.subs.get(symbol)
        return sub[-1].close if sub else None

    def place_bracket(self, symbol: str, qty: int, limit: float, target: float, stop: float):
        orders = self.ib.bracketOrder("BUY", qty, limitPrice=limit, takeProfitPrice=target, stopLossPrice=stop)
        contract = self._contract(symbol)
        trades = [self.ib.placeOrder(contract, o) for o in orders]
        return {"parent": trades[0], "target": trades[1], "stop": trades[2]}

    @staticmethod
    def _filled(trade) -> tuple[bool, float | None]:
        st = trade.orderStatus
        return st.status == "Filled", (st.avgFillPrice or None)

    def status(self, h) -> dict:
        entry_done, entry_px = self._filled(h["parent"])
        out = {"filled": entry_done, "fill": entry_px, "exit": None, "exit_price": None,
               "dead": h["parent"].orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive")}
        for name in ("target", "stop"):
            done, px = self._filled(h[name])
            if done:
                out["exit"], out["exit_price"] = name, px
        return out

    def cancel(self, h) -> None:
        for name in ("parent", "target", "stop"):
            try:
                if h[name].orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled"):
                    self.ib.cancelOrder(h[name].order)
            except Exception as e:
                log.debug("cancel %s: %s", name, e)

    def flatten(self, symbol: str, h, qty: int) -> float | None:
        """Cancel the bracket and sell the position at market; returns the exit price."""
        from ib_async import MarketOrder
        self.cancel(h)
        self.ib.sleep(1)
        trade = self.ib.placeOrder(self._contract(symbol), MarketOrder("SELL", qty))
        for _ in range(30):
            self.ib.sleep(1)
            if trade.orderStatus.status == "Filled":
                return trade.orderStatus.avgFillPrice
        return self.last_price(symbol)

    def disconnect(self) -> None:
        if self.ib is not None:
            self.ib.disconnect()


class ReplayBroker:
    """Plays a past session back through the trader: real IBKR 1-minute bars, simulated fills.

    No orders are sent. The clock moves one minute per loop (TRADER_REPLAY_SPEED real seconds each),
    so a whole morning plays in a few minutes on the stream panel.
    """

    def __init__(self, day: datetime, symbols: list[str] | None = None, speed: float = 1.0):
        self.day, self.symbols, self.speed = day, symbols or [], speed
        self.now = et_time("09:30", day)
        self.data: dict[str, list[tr.Bar]] = {}
        self.orders: list[dict] = []
        self.ib = None

    def clock(self) -> datetime:
        return self.now

    def connect(self) -> list[str]:
        import ibkr
        from ib_async import IB, Stock
        self.ib = IB()
        self.ib.connect(ibkr.host(), ibkr.port(), clientId=int(env_float("TRADER_CLIENT_ID", 31)) + 1,
                        readonly=True, timeout=env_float("IB_CONNECT_TIMEOUT", 20))
        accounts = self.ib.managedAccounts()
        ibkr.check_paper(accounts)
        if not self.symbols:
            try:
                self.symbols = IBBroker.scan(self, int(env_float("TRADER_CANDIDATES", 6)))[:6]
            except Exception as e:
                log.warning("[replay] scanner unavailable (%s) - using a default list", e)
        if not self.symbols:
            self.symbols = ["NVDA", "TSLA", "AMD", "PLTR", "SOFI", "SMCI"]
        end = self.day.strftime("%Y%m%d") + " 16:00:00 US/Eastern"
        for sym in self.symbols:
            try:
                c = Stock(sym, "SMART", "USD")
                self.ib.qualifyContracts(c)
                raw = self.ib.reqHistoricalData(c, end, "1 D", "1 min", "TRADES", useRTH=True)
                self.data[sym] = [tr.Bar(str(b.date), b.open, b.high, b.low, b.close, b.volume) for b in raw]
                log.info("[replay] %s: %d bars", sym, len(self.data[sym]))
            except Exception as e:
                log.warning("[replay] no bars for %s: %s", sym, e)
        if not any(self.data.values()):
            raise RuntimeError("IBKR returned no historical bars - is market data enabled for the paper account?")
        return accounts

    def connected(self) -> bool:
        return True

    def sleep(self, seconds: float) -> None:
        time.sleep(self.speed)
        self.now += timedelta(minutes=1)

    def _index(self) -> int:
        return int((self.now - et_time("09:30", self.now)).total_seconds() // 60)

    def scan(self, rows: int) -> list[str]:
        return [s for s in self.symbols if self.data.get(s)][:rows]

    def bars(self, symbol: str) -> list[tr.Bar]:
        return self.data.get(symbol, [])[:max(0, self._index())]

    def last_price(self, symbol: str) -> float | None:
        b = self.bars(symbol)
        return b[-1].close if b else None

    def place_bracket(self, symbol, qty, limit, target, stop):
        h = {"symbol": symbol, "limit": limit, "target": target, "stop": stop, "from": self._index(),
             "fill": None, "exit": None, "exit_price": None}
        self.orders.append(h)
        return h

    def status(self, h) -> dict:
        bars = self.data.get(h["symbol"], [])[h["from"]:self._index()]
        for b in bars:
            if h["fill"] is None:
                if b.low <= h["limit"]:
                    h["fill"] = min(h["limit"], b.open)
                continue
            if h["exit"] is None:
                if b.low <= h["stop"]:  # stop first if a bar hits both: the cautious assumption
                    h["exit"], h["exit_price"] = "stop", h["stop"]
                elif b.high >= h["target"]:
                    h["exit"], h["exit_price"] = "target", h["target"]
        h["from"] = self._index()
        return {"filled": h["fill"] is not None, "fill": h["fill"], "dead": False,
                "exit": h["exit"], "exit_price": h["exit_price"]}

    def cancel(self, h) -> None:
        pass

    def flatten(self, symbol, h, qty) -> float | None:
        return self.last_price(symbol)

    def disconnect(self) -> None:
        if self.ib is not None:
            self.ib.disconnect()


def simulated_session(symbol: str, seed: int, bars: int = 390) -> list[tr.Bar]:
    """Made-up but realistic 1-minute bars: a gapper that either breaks out, fakes out, or dips
    under VWAP and reclaims it - so the rules have something to trade at any time of day."""
    import random
    rnd = random.Random(seed)
    price = rnd.uniform(4, 60)
    style = rnd.choice(["breakout", "fakeout", "reclaim", "chop"])
    vol0 = rnd.uniform(20_000, 120_000)
    out, t0 = [], datetime(2000, 1, 1, 9, 30)
    for i in range(bars):
        drift, vol_mult = 0.0, 1.0
        if style == "breakout" and 6 <= i < 40:
            drift, vol_mult = 0.004, (3.0 if i == 6 else 1.6)
        elif style == "fakeout" and i == 6:
            drift, vol_mult = 0.006, 3.0
        elif style == "fakeout" and 7 <= i < 20:
            drift = -0.004
        elif style == "reclaim" and 5 <= i < 25:
            drift = -0.003
        elif style == "reclaim" and i == 25:
            drift, vol_mult = 0.012, 3.5
        elif style == "reclaim" and 26 <= i < 70:
            drift, vol_mult = 0.002, 1.4
        decay = 1.8 if i < 30 else 1.0  # busy open, quieter later
        change = drift + rnd.gauss(0, 0.0025)
        o = price
        c = max(0.5, o * (1 + change))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.001)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.001)))
        v = vol0 * decay * vol_mult * rnd.uniform(0.6, 1.4)
        out.append(tr.Bar((t0 + timedelta(minutes=i)).strftime("%H:%M"), round(o, 2), round(h, 2),
                          round(l, 2), round(c, 2), round(v)))
        price = c
    return out


class SimBroker(ReplayBroker):
    """Simulated tickers: no IB Gateway or market data needed - for demos and testing any time."""

    def connect(self) -> list[str]:
        import random
        seed = int(env_float("TRADER_SIM_SEED", 0)) or random.randrange(1, 10**6)
        names = ["SIMA", "SIMB", "SIMC", "SIMD", "SIME", "SIMF"]
        self.symbols = self.symbols or names
        self.data = {sym: simulated_session(sym, seed + i) for i, sym in enumerate(self.symbols)}
        log.info("[sim] simulated session, seed %s", seed)
        return ["SIMULATED"]

    def disconnect(self) -> None:
        pass


def last_session(now: datetime) -> datetime:
    """The most recent weekday session that has finished (US holidays aren't skipped)."""
    day = now if now.weekday() < 5 and now >= et_time("16:05", now) else now - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------- trader

class Trader:
    def __init__(self, live_root: Path, broker, watch_only: bool = False, stop_file: Path | None = None,
                 clock=None, replay: bool = False, journal_root: Path | None = None, simulated: bool = False):
        self.root = live_root
        self.replay = replay
        self.simulated = simulated
        self.journal_root = journal_root or live_root
        self.broker = broker
        self.watch_only = watch_only
        self.stop_file = stop_file
        self.clock = clock or (lambda: datetime.now(eastern()))
        self.book = tr.DayBook(max_trades=int(env_float("TRADER_MAX_TRADES", 5)),
                               max_losses=int(env_float("TRADER_MAX_LOSSES", 3)))
        self.watching: list[str] = []
        self.open: dict | None = None
        self.captions: list[dict] = []
        self.last_scan = 0.0
        self.announced_limit = False
        self.phase = "starting"
        self.day = self.clock().strftime("%Y-%m-%d")
        self._load_today()

    # ------------------------------------------------------------------ narration / state
    def say(self, text: str) -> None:
        log.info("[trader] %s", text)
        self.captions.append({"at": self.clock().strftime("%H:%M"), "text": text})
        self.captions = self.captions[-8:]
        self.save()

    def journal_path(self) -> Path:
        return self.journal_root / self.day / "trades.json"

    def _load_today(self) -> None:
        try:
            self.book.trades = json.loads(self.journal_path().read_text(encoding="utf-8"))
        except Exception:
            self.book.trades = []

    def save(self) -> None:
        unreal = None
        if self.open and self.open.get("fill"):
            px = self.broker.last_price(self.open["symbol"])
            if px:
                unreal = round((px - self.open["fill"]) * self.open["qty"], 2)
        state = {
            "phase": self.phase, "mode": ("simulation" if self.simulated else "replay" if self.replay
                                          else "watch" if self.watch_only else "paper"),
            "watching": self.watching[:8], "position": self._public(self.open, unreal),
            "trades": self.book.trades[-10:], "stats": {
                "trades": len(self.book.trades), "max_trades": self.book.max_trades,
                "wins": self.book.wins, "losses": self.book.losses, "max_losses": self.book.max_losses,
                "pnl": self.book.pnl, "unrealized": unreal},
            "captions": self.captions, "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / f"trader.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(self.root / "trader.json")
            self.journal_path().parent.mkdir(parents=True, exist_ok=True)
            self.journal_path().write_text(json.dumps(self.book.trades, indent=2), encoding="utf-8")
        except OSError as e:
            log.debug("trader state not saved: %s", e)

    @staticmethod
    def _public(pos: dict | None, unreal) -> dict | None:
        if not pos:
            return None
        keys = ("symbol", "strategy", "qty", "entry", "stop", "target", "fill", "reason", "state")
        return {**{k: pos.get(k) for k in keys}, "unrealized": unreal}

    # ------------------------------------------------------------------ main loop
    def stopping(self) -> bool:
        return self.stop_file is not None and self.stop_file.exists()

    def run(self) -> int:
        self.phase = "connecting"
        self.save()
        accounts = self.broker.connect()
        if self.simulated:
            self.say("SIMULATION: made-up tickers and prices to show how the AI trader works - "
                     "not real market data, no orders.")
        elif self.replay:
            self.say(f"REPLAY of {self.clock():%A %b %d}: real 1-minute bars, simulated fills, no orders. "
                     "Watch how the rules would have traded it.")
        self.say(f"AI paper trader online - paper account {accounts[0]}. "
                 f"Today's rules: max {self.book.max_trades} trades, stop after {self.book.max_losses} losses."
                 + (" Watch-only mode: no orders." if self.watch_only else ""))
        try:
            while not self.stopping():
                now = self.clock()
                if now >= et_time(env("TRADER_FLATTEN_ET", "15:50") or "15:50", now):
                    self.say("Flatten time - closing out for the day.")
                    break
                if self.replay and not self.open and now >= et_time(env("TRADER_REPLAY_END", "12:00") or "12:00", now):
                    break
                try:
                    self.step(now)
                except Exception as e:
                    log.error("[trader] step failed: %s", e)
                    if not self.broker.connected():
                        self.say("Lost the connection to IB Gateway - reconnecting.")
                        self.broker.connect()
                self.broker.sleep(env_float("TRADER_LOOP_SECONDS", 15))
        finally:
            self.close_out()
            self.recap()
            self.broker.disconnect()
        return 0

    def step(self, now: datetime) -> None:
        if now.weekday() >= 5:
            if self.phase != "closed":
                self.phase = "closed"
                self.say("The market is closed today - no trades. See you on the next trading day.")
            return
        open_ = et_time("09:30", now)
        orb_min = int(env_float("TRADER_ORB_MIN", 5))
        if now < open_:
            self.phase = "pre-market"
            self.scan(now, every=300)
            return
        if self.open:
            self.manage(now)
        self.scan(now, every=env_float("TRADER_RESCAN_SECONDS", 300))
        if now < open_ + timedelta(minutes=orb_min + 1):
            self.phase = "opening range"
            self.save()
            return
        ok, why = self.book.can_trade()
        if not ok:
            self.phase = "done for the day"
            if not self.announced_limit:
                self.announced_limit = True
                self.say(why.capitalize() + ", as the rules say. I'll keep commenting but take no more trades.")
            return
        if now >= et_time(env("TRADER_LAST_ENTRY_ET", "11:30") or "11:30", now):
            self.phase = "no new trades"
            self.save()
            return
        if not self.open:
            self.look_for_entry(now)
        self.phase = "in a trade" if self.open else "hunting"
        self.save()

    def scan(self, now: datetime, every: float) -> None:
        if self.clock().timestamp() - self.last_scan < every and self.watching:
            return
        self.last_scan = self.clock().timestamp()
        rows = int(env_float("TRADER_CANDIDATES", 6))
        try:
            found = self.broker.scan(rows * 2)
        except Exception as e:
            log.warning("[trader] scanner failed: %s", e)
            return
        new = [s for s in found if s not in self.watching][:rows]
        self.watching = (self.watching + new)[-rows:] if self.watching else found[:rows]
        if new:
            self.say("On the scanner: " + ", ".join(new[:5]) + ". Watching for "
                     + " and ".join({"orb": "opening-range breakouts", "vwap": "VWAP reclaims"}[s]
                                    for s in strategies()) + ".")

    def look_for_entry(self, now: datetime) -> None:
        for symbol in self.watching:
            if self.book.traded(symbol):
                continue
            try:
                bars = self.broker.bars(symbol)
            except Exception as e:
                log.debug("[trader] no bars for %s: %s", symbol, e)
                continue
            sig = tr.find_signal(symbol, bars, strategies(), orb_min=int(env_float("TRADER_ORB_MIN", 5)),
                                 target_r=env_float("TRADER_TARGET_R", 2))
            if sig:
                self.enter(sig, now)
                return

    def enter(self, sig: tr.Signal, now: datetime) -> None:
        qty = tr.position_size(sig.entry, sig.stop, env_float("TRADER_RISK_USD", 100),
                               env_float("TRADER_MAX_POSITION_USD", 10000))
        if qty < 1:
            return
        plan = (f"{sig.symbol} {sig.strategy}: {sig.reason}. Long {qty} shares near {sig.entry:.2f}, "
                f"stop {sig.stop:.2f}, target {sig.target:.2f} - risking about "
                f"${qty * sig.risk:.0f} to make ${qty * (sig.target - sig.entry):.0f}.")
        record = {"symbol": sig.symbol, "strategy": sig.strategy, "qty": qty, "entry": sig.entry,
                  "stop": sig.stop, "target": sig.target, "reason": sig.reason, "opened": now.isoformat(),
                  "fill": None, "exit": None, "pnl": None, "result": None}
        if self.watch_only:
            self.say("Setup (watch only, no order): " + plan)
            self.book.trades.append({**record, "result": "watch only", "pnl": 0.0})
            return
        limit = tr.tick_round(sig.entry * (1 + env_float("TRADER_ENTRY_SLIP", 0.002)))
        handle = self.broker.place_bracket(sig.symbol, qty, limit, sig.target, sig.stop)
        self.open = {**record, "handle": handle, "placed": self.clock().timestamp(), "state": "entry order sent"}
        self.say("Taking a paper trade - " + plan)

    def manage(self, now: datetime) -> None:
        pos = self.open
        st = self.broker.status(pos["handle"])
        if not pos.get("fill"):
            if st["filled"]:
                pos["fill"], pos["state"] = st["fill"] or pos["entry"], "in the trade"
                self.say(f"Filled {pos['symbol']} at {pos['fill']:.2f}. Stop {pos['stop']:.2f}, "
                         f"target {pos['target']:.2f}.")
            elif st["dead"] or self.clock().timestamp() - pos["placed"] > env_float("TRADER_FILL_TIMEOUT", 90):
                self.broker.cancel(pos["handle"])
                self.say(f"{pos['symbol']} ran without us - the entry didn't fill, so the order is cancelled. "
                         "No trade.")
                self.open = None
                return
        if pos.get("fill") and st["exit"]:
            self.finish(st["exit"], st["exit_price"] or (pos["target"] if st["exit"] == "target" else pos["stop"]))

    def finish(self, how: str, price: float) -> None:
        pos = self.open
        pnl = round((price - pos["fill"]) * pos["qty"], 2)
        r = (price - pos["fill"]) / max(pos["entry"] - pos["stop"], 1e-9)
        result = "win" if pnl > 0 else "loss" if pnl < 0 else "scratch"
        rec = {k: v for k, v in pos.items() if k not in ("handle", "placed", "state")}
        rec.update(exit=price, pnl=pnl, r=round(r, 2), result=result, how=how,
                   closed=self.clock().isoformat())
        self.book.trades.append(rec)
        self.open = None
        words = {"target": "hit the target", "stop": "stopped out", "flatten": "closed at the end of the session"}
        self.say(f"{rec['symbol']} {words.get(how, how)} at {price:.2f}: {'+' if pnl >= 0 else '-'}${abs(pnl):.0f} "
                 f"({r:+.1f}R). Day: {self.book.wins}W/{self.book.losses}L, "
                 f"{'+' if self.book.pnl >= 0 else '-'}${abs(self.book.pnl):.0f}.")

    def close_out(self) -> None:
        if not self.open:
            return
        pos = self.open
        if pos.get("fill"):
            price = self.broker.flatten(pos["symbol"], pos["handle"], pos["qty"]) or pos["fill"]
            self.finish("flatten", price)
        else:
            self.broker.cancel(pos["handle"])
            self.open = None

    def recap(self) -> None:
        real = [t for t in self.book.trades if t.get("result") in ("win", "loss", "scratch")]
        if not real:
            self.say("No trades today. Sometimes the best trade is no trade.")
        else:
            self.say(f"That's the session: {len(real)} paper trades, {self.book.wins} wins, {self.book.losses} losses, "
                     f"{'+' if self.book.pnl >= 0 else '-'}${abs(self.book.pnl):.0f}. Paper trading - "
                     "educational, not financial advice.")
        self.phase = "finished"
        self.save()


# --------------------------------------------------------------------------- overlay server

def serve_overlay(live_root: Path, port: int | None = None) -> threading.Thread | None:
    """http://127.0.0.1:47622/ - the OBS browser source; /state is Live/trader.json."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    port = port or int(env_float("TRADER_OVERLAY_PORT", 47622))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/state"):
                try:
                    body = (live_root / "trader.json").read_bytes()
                except OSError:
                    body = b"{}"
                ctype = "application/json"
            else:
                body, ctype = OVERLAY_FILE.read_bytes(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        log.warning("[trader] overlay port %s busy (%s) - is another trader running?", port, e)
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def overlay_url() -> str:
    return f"http://127.0.0.1:{int(env_float('TRADER_OVERLAY_PORT', 47622))}/"


def keep_panel_up(stop: Path, rc: int) -> int:
    """After a replay / simulation, leave the panel (with the recap) up for a while."""
    end = time.monotonic() + env_float("TRADER_PANEL_LINGER", 600)
    while time.monotonic() < end and not stop.exists():
        time.sleep(1)
    return rc


def main(argv: list[str] | None = None) -> int:
    from live import live_root
    from watcher import setup_logging
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "overlay", "replay", "simulate"])
    ap.add_argument("--date", help="replay: YYYY-MM-DD (default: the last trading day)")
    ap.add_argument("--symbols", help="replay: comma-separated symbols (default: IBKR scanner)")
    ap.add_argument("--watch", action="store_true", help="signals and commentary only, no orders")
    ap.add_argument("--stop-file")
    args = ap.parse_args(argv)
    try:
        settings = Settings.load()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    setup_logging(settings, False)
    root = live_root(settings)
    serve_overlay(root)
    if args.command == "overlay":
        print(f"overlay at {overlay_url()} - Ctrl+C to stop")
        while True:
            time.sleep(1)
    stop = Path(args.stop_file) if args.stop_file else root / "TRADER_STOP"
    stop.unlink(missing_ok=True)
    if args.command == "simulate":
        now = datetime.now(eastern())
        day = now if now.weekday() < 5 else last_session(now)
        broker = SimBroker(day, None, speed=env_float("TRADER_REPLAY_SPEED", 1.0))
        print(f"simulated session - watch it at {overlay_url()}")
        journal = root / "replay"
        (journal / day.strftime("%Y-%m-%d") / "trades.json").unlink(missing_ok=True)
        rc = Trader(root, broker, stop_file=stop, clock=broker.clock, replay=True, journal_root=journal,
                    simulated=True).run()
        return keep_panel_up(stop, rc)
    if args.command == "replay":
        day = (datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=eastern()) if args.date
               else last_session(datetime.now(eastern())))
        symbols = [x.strip().upper() for x in (args.symbols or "").split(",") if x.strip()]
        broker = ReplayBroker(day, symbols, speed=env_float("TRADER_REPLAY_SPEED", 1.0))
        print(f"replaying {day:%A %Y-%m-%d} - watch it at {overlay_url()}")
        # The replay keeps its own journal folder so it never mixes with real paper trades.
        journal = root / "replay"
        (journal / day.strftime("%Y-%m-%d") / "trades.json").unlink(missing_ok=True)  # start the replay fresh
        rc = Trader(root, broker, stop_file=stop, clock=broker.clock, replay=True, journal_root=journal).run()
        return keep_panel_up(stop, rc)
    watch = args.watch or (env("TRADER_MODE", "paper") or "paper").lower() == "watch"
    return Trader(root, IBBroker(readonly=watch), watch_only=watch, stop_file=stop).run()


if __name__ == "__main__":
    sys.exit(main())
