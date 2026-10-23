"""Autonomous trading cycle. Scheduled every 5 minutes; exits in well under a second when the
market is closed (heavy imports happen only after the time gate passes).

Order of work each run:
 1 time gate  2 load state  3 stop-outs / reconcile with IBKR  4 manage open positions
 5 save  6 force-close (15:51+)  7 manage-only windows  8 entry scan  9 save + disconnect
"""
from __future__ import annotations

import math
import sys
import time as _time
import traceback
from datetime import datetime, time, timedelta

from src.common import (LOGS_DIR, PAUSE_PATH, SAFETY_LOG_PATH, WATCHLIST_PATH, append_jsonl, append_trade, check_paper_live_guard,
                        env_float, env_int, env_str, load_positions, load_rules, now_et, read_trades, read_watchlist,
                        save_positions, todays_buy_count, ts)

SESSION_START = time(9, 30)  # strategies like ORB can trade from the open
SESSION_END = time(16, 0)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def entry_window(rules: dict) -> tuple[time, time]:
    """Earliest/latest entry across the ACTIVE strategies (each still checks its own window)."""
    from src import strategies as st
    cfgs = [st.config(x, rules) for x in st.load() if x.get("enabled")]
    if not cfgs:
        return time(23, 59), time(0, 0)  # nothing active: manage only
    return (min(_hhmm(c["earliest_entry_et"]) for c in cfgs), max(_hhmm(c["latest_entry_et"]) for c in cfgs))


def time_gate(now: datetime, rules: dict, window: tuple[time, time] | None = None) -> str:
    tf = rules["time_filter"]
    t = now.time()
    if now.weekday() >= 5:
        return "weekend"
    if t < SESSION_START:
        return "too_early"
    if t >= SESSION_END:
        return "closed"
    if t >= _hhmm(tf["force_close_et"]):
        return "force_close"
    earliest, latest = window or (_hhmm(tf["earliest_entry_et"]), _hhmm(tf["latest_entry_et"]))
    if t < earliest or t > latest:
        return "manage_only"
    return "ok"


def log(event: str, **fields) -> None:
    append_jsonl(SAFETY_LOG_PATH, {"event": event, **fields})
    print(f"{ts()} {event} {fields if fields else ''}", flush=True)


def safe_notify(title: str, body: str, priority: str = "default") -> None:
    try:
        from src.notify import notify
        notify(title, body, priority)
    except Exception:
        pass


def connect():
    from src.ibkr_client import IBKRClient
    host, port, cid = env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), env_int("IBKR_CLIENT_ID", 2)
    try:
        return IBKRClient(host, port, cid)
    except Exception as exc:
        log("connect_retry", error=repr(exc))
        _time.sleep(5)
        return IBKRClient(host, port, cid)


def current_price(ibkr, symbol: str, bars=None) -> float:
    try:
        p = ibkr.last_price(symbol)
        if not math.isnan(p):
            return p
    except Exception:
        pass
    if bars is None:
        from src.marketdata import intraday_bars
        bars = intraday_bars(symbol, period="1d")
    return float(bars["Close"].iloc[-1]) if bars is not None and not bars.empty else float("nan")


# ---------------------------------------------------------------- step 3: stop-outs / reconcile

def _dir(pos: dict) -> int:
    """+1 for a long position, -1 for a short."""
    return -1 if pos.get("side") == "short" else 1


def _close_side(pos: dict) -> str:
    return "BUY" if _dir(pos) < 0 else "SELL"


def stop_fills(ibkr, pos: dict) -> tuple[int, float]:
    """Shares and avg price filled on this position's stop order. Matches by order id / permId,
    never by quantity (quantity matching gives false stop-outs after a partial)."""
    since = datetime.now().astimezone() - timedelta(hours=8)
    shares, notional = 0.0, 0.0
    exec_side = "BOT" if _dir(pos) < 0 else "SLD"  # a short's stop buys to cover
    for f in ibkr.ib.fills():
        ex = f.execution
        acct = getattr(ex, "acctNumber", "")
        if f.contract.symbol != pos["symbol"] or ex.side != exec_side or acct not in ("", getattr(ibkr, "account", acct)):
            continue
        if ex.orderId != pos.get("stop_order_id") and (not pos.get("stop_perm_id") or ex.permId != pos["stop_perm_id"]):
            continue
        if f.time and f.time < since:
            continue
        shares += ex.shares
        notional += ex.shares * ex.price
    return int(shares), (notional / shares if shares else 0.0)


def reconcile(ibkr, positions: list[dict]) -> list[dict]:
    keep = []
    for pos in positions:
        sym, d = pos["symbol"], _dir(pos)
        held = ibkr.position_qty(sym) * d  # >0 while the position (long or short) is still open
        filled, px = stop_fills(ibkr, pos)
        if filled and held <= 0:
            pnl = (px - pos["entry_price"]) * filled * d
            append_trade({"timestamp_iso": now_et().isoformat(timespec="seconds"), "symbol": sym, "side": _close_side(pos),
                          "size": filled, "fill_price": round(px, 4), "order_id": pos["stop_order_id"], "status": "StopFilled",
                          "strategy": pos.get("strategy", "")})
            log("stopped_out", symbol=sym, side=pos.get("side", "long"), qty=filled, exit=px, pnl=pnl)
            safe_notify(f"STOP {sym}", f"exit ${px:.2f}, P&L ${pnl:+.2f}")
            continue
        if held <= 0:
            log("position_gone", symbol=sym, note="not held in IBKR and no stop fill found; closed outside the bot?")
            ibkr.cancel(pos.get("stop_order_id"))
            safe_notify(f"GONE {sym}", "position no longer in IBKR; removed from bot state", "high")
            continue
        if held != pos["qty"]:
            log("qty_mismatch", symbol=sym, state_qty=pos["qty"], ibkr_qty=held)
            pos["qty"] = held
            ibkr.modify_stop(sym, pos.get("stop_order_id"), held, pos["stop"], action=_close_side(pos))
        keep.append(pos)
    return keep


def adopt_orphans(ibkr, positions: list[dict], rules: dict) -> None:
    """An entry the bot logged today that IBKR holds but state doesn't know about (e.g. trade.py
    timed out before the fill came back). Give it a stop instead of leaving it naked."""
    from src.filters import initial_stop
    from src.marketdata import intraday_bars
    from src.filters import _rth, _day

    known = {p["symbol"] for p in positions}
    today = now_et().date().isoformat()
    entries = {r["symbol"]: r for r in read_trades() if r["timestamp_iso"].startswith(today) and is_entry_row(r)}
    for sym, row in entries.items():
        if sym in known:
            continue
        side = "short" if row["side"] == "SELL" else "long"
        qty = ibkr.position_qty(sym) * (-1 if side == "short" else 1)
        if qty <= 0:
            continue
        entry = float(row.get("fill_price") or 0) or current_price(ibkr, sym)
        stop = float(row["stop_price"]) if row.get("stop_price") else None
        if stop is None:
            bars = _day(_rth(intraday_bars(sym, period="1d")), now_et().date())
            stop = initial_stop(float(bars["Low"].min()), rules["exit"]["initial_stop_rule"])
        t = ibkr.place_stop(sym, qty, stop, action="BUY" if side == "short" else "SELL")
        positions.append(new_position(sym, entry, qty, stop, t, strategy=row.get("strategy") or "trend_join_long", side=side))
        log("orphan_adopted", symbol=sym, side=side, qty=qty, entry=entry, stop=stop, stop_order_id=t.order.orderId)
        safe_notify(f"ADOPTED {sym}", f"{qty} sh {side} had no stop; stop ${stop:.2f} placed", "high")


def is_entry_row(r: dict) -> bool:
    """trades.csv: entries carry the initial stop; old rows (before strategies) were all-long BUYs."""
    return bool(r.get("stop_price")) or (r.get("side") == "BUY" and not r.get("strategy"))


def new_position(sym: str, entry: float, qty: int, stop: float, stop_trade,
                 strategy: str = "trend_join_long", exit_rules: dict | None = None, side: str = "long") -> dict:
    return {"symbol": sym, "side": side, "entry_price": entry, "entry_time_iso": now_et().isoformat(timespec="seconds"),
            "qty": qty, "initial_stop": stop, "stop": stop, "stop_order_id": stop_trade.order.orderId,
            "stop_perm_id": stop_trade.order.permId, "state": "pre_breakeven", "partial_done": False,
            "R": abs(entry - stop), "strategy": strategy, "exit": exit_rules}


# ---------------------------------------------------------------- step 4: manage

def manage(ibkr, positions: list[dict], rules: dict) -> None:
    """Partial, breakeven, trailing stop and optional full target. Longs and shorts are mirrored:
    d = +1 (long) / -1 (short); 'gain' below is always in the trade's favour."""
    from src.executor import run_trade
    from src.filters import _rth, swing_highs, swing_lows
    from src.marketdata import intraday_bars

    for pos in positions:
        ex = {"take_profit_R": 0, "trail": True, **rules["exit"], **(pos.get("exit") or {})}
        sym, entry, R, d = pos["symbol"], pos["entry_price"], pos["R"], _dir(pos)
        close, stop_action, strategy = _close_side(pos), _close_side(pos), pos.get("strategy", "")
        bars = intraday_bars(sym, period="1d")
        price = current_price(ibkr, sym, bars)
        if math.isnan(price) or R <= 0:
            log("manage_skip", symbol=sym, reason="no price or bad R")
            continue
        gain = (price - entry) * d  # in the trade's favour

        if ex.get("take_profit_R") and gain >= float(ex["take_profit_R"]) * R:
            ibkr.cancel(pos.get("stop_order_id"))
            result, out = run_trade(sym, close, pos["qty"], strategy=strategy)
            if result and result.get("status") == "Filled":
                pos["closed"] = True
                log("take_profit", symbol=sym, qty=pos["qty"], price=result["fill_price"], strategy=strategy)
                safe_notify(f"TARGET {sym}", f"closed {pos['qty']} @ ${result['fill_price']:.2f} (+{ex['take_profit_R']}R)")
            else:
                t = ibkr.place_stop(sym, pos["qty"], pos["stop"], action=stop_action)
                pos.update(stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
                log("take_profit_failed", symbol=sym, output=out[-500:])
            continue

        # partial first: checking breakeven first means a stock that jumps straight past it never banks its partial
        if not pos["partial_done"] and gain >= ex["partial_profit_trigger_R"] * R and pos["qty"] > 1:
            part = min(pos["qty"] - 1, math.ceil(pos["qty"] * ex["partial_profit_fraction"]))
            remaining = pos["qty"] - part
            # Shrink the stop BEFORE taking the partial so it can never be larger than the position
            # (which would flip it if it triggered).
            ibkr.modify_stop(sym, pos["stop_order_id"], remaining, pos["stop"], action=stop_action)
            result, out = run_trade(sym, close, part, strategy=strategy)
            if result and result.get("filled"):
                done = int(result["filled"])
                pos["qty"] = pos["qty"] - done
                pos["partial_done"] = True
                pos["state"] = "partial_done" if pos["state"] == "pre_breakeven" else pos["state"]
                # Trend Join Long: after the partial, tighten the stop to entry - 1% (ratchet up only).
                tight = round(entry * 0.99, 2)
                if strategy in ("", "trend_join_long") and d > 0 and tight > pos["stop"]:
                    t = ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], tight, action=stop_action)
                    pos.update(stop=tight, stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
                log("partial", symbol=sym, side=pos.get("side", "long"), qty=done, price=result["fill_price"],
                    remaining=pos["qty"], stop=pos["stop"])
                safe_notify(f"PARTIAL {sym}", f"took {done}/{done + pos['qty']} @ ${result['fill_price']:.2f}")
            else:
                ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], pos["stop"], action=stop_action)
                log("partial_failed", symbol=sym, output=out[-500:])

        if pos["state"] != "post_breakeven" and gain >= ex["breakeven_trigger_R"] * R and (entry - pos["stop"]) * d > 0:
            t = ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], entry, action=stop_action)
            pos.update(stop=entry, stop_order_id=t.order.orderId, stop_perm_id=t.order.permId, state="post_breakeven")
            log("breakeven", symbol=sym, new_stop=entry)
            safe_notify(f"BE {sym}", f"stop -> ${entry:.2f}")

        if pos["state"] == "post_breakeven" and ex.get("trail", True) and bars is not None and not bars.empty:
            entry_time = datetime.fromisoformat(pos["entry_time_iso"])
            completed = _rth(bars).iloc[:-1]  # newest bar is still forming
            if d > 0:  # long: trail under swing lows, only ever up
                pts = [(t, v) for t, v in swing_lows(completed, 2, 2) if t >= entry_time]
                new_stop = round(pts[-1][1] - 0.01, 2) if pts else None
                better = new_stop is not None and pos["stop"] < new_stop < price
            else:      # short: trail above swing highs, only ever down
                pts = [(t, v) for t, v in swing_highs(completed, 2, 2) if t >= entry_time]
                new_stop = round(pts[-1][1] + 0.01, 2) if pts else None
                better = new_stop is not None and price < new_stop < pos["stop"]
            if better:
                old = pos["stop"]
                t = ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], new_stop, action=stop_action)
                pos.update(stop=new_stop, stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
                log("trail", symbol=sym, old_stop=old, new_stop=new_stop)
                safe_notify(f"TRAIL {sym}", f"stop ${old:.2f} -> ${new_stop:.2f}")
    positions[:] = [p for p in positions if not p.get("closed")]


# ---------------------------------------------------------------- step 6: force close

def force_close(ibkr, positions: list[dict]) -> list[dict]:
    from src.executor import run_trade

    if positions:
        safe_notify("EOD Force Close", f"flattening {len(positions)} positions", "high")
    left = []
    for pos in positions:
        sym = pos["symbol"]
        ibkr.cancel(pos.get("stop_order_id"))
        qty = ibkr.position_qty(sym) * _dir(pos)
        if qty <= 0:
            log("force_close_nothing_held", symbol=sym)
            continue
        result, out = run_trade(sym, _close_side(pos), qty, strategy=pos.get("strategy", ""))
        if result and result.get("status") == "Filled":
            log("force_closed", symbol=sym, side=pos.get("side", "long"), qty=qty, price=result["fill_price"])
        else:
            # Put the protective stop back so nothing sits naked; next run retries the close.
            t = ibkr.place_stop(sym, qty, pos["stop"], action=_close_side(pos))
            pos.update(stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
            left.append(pos)
            log("force_close_failed", symbol=sym, output=out[-500:])
            safe_notify(f"FORCE CLOSE FAILED {sym}", "stop re-placed; will retry next cycle", "high")
    return left


# ---------------------------------------------------------------- step 8: entries

def _round_price(x: float) -> float:
    return round(float(x), 2) if x >= 1 else round(float(x), 4)


def entry_scan(ibkr, positions: list[dict], rules: dict) -> None:
    """Run every ACTIVE strategy over its stocks; buy what passes, within global and per-strategy limits."""
    from src import strategies as st
    from src.executor import run_trade
    from src.filters import position_size
    from src.marketdata import daily_bars, intraday_bars

    max_trades = env_int("MAX_TRADES_PER_DAY", 5)
    max_open = int(rules["risk"]["max_concurrent_positions"])
    buys = todays_buy_count()
    if buys >= max_trades:
        log("entry_skip", reason=f"daily trade cap {buys}/{max_trades}")
        return

    now = now_et()
    today, now_t = now.date(), now.time()
    watchlist_fresh = WATCHLIST_PATH.exists() and \
        datetime.fromtimestamp(WATCHLIST_PATH.stat().st_mtime, now.tzinfo).date() == today
    held = ibkr.held_symbols() | {p["symbol"] for p in positions}  # IBKR first: avoids double entries
    portfolio = env_float("PORTFOLIO_VALUE_USD", 25000)
    data_cache: dict[str, tuple] = {}  # one download per symbol per cycle, shared by strategies

    for strat in [x for x in st.load() if x.get("enabled")]:
        cfg = st.config(strat, rules)
        sid = cfg["id"]
        if not (_hhmm(cfg["earliest_entry_et"]) <= now_t <= _hhmm(cfg["latest_entry_et"])):
            continue
        if cfg.get("timeframe", "5m") == "5m" and now.minute % 5:
            continue  # the cycle runs every minute; 5-minute strategies only look on 5-minute marks
        s_buys = todays_buy_count(strategy=sid)
        if s_buys >= cfg["max_trades_per_day"]:
            log("entry_skip", strategy=sid, reason=f"strategy daily cap {s_buys}/{cfg['max_trades_per_day']}")
            continue
        if cfg["universe"] == "gappers":
            if not watchlist_fresh:
                log("entry_skip", strategy=sid, reason="watchlist.txt missing or not from today; run morning_prefilter.py")
                continue
            symbols = read_watchlist()
        else:
            symbols = cfg["tickers"]
        risk_pct = cfg["risk_pct"] if cfg["type"] != "trend_join" else \
            env_float("MAX_RISK_PER_TRADE_PCT", float(rules["risk"]["max_risk_per_trade_pct"]))

        for sym in symbols:
            if buys >= max_trades or len(positions) >= max_open or s_buys >= cfg["max_trades_per_day"]:
                break
            if sym in held:
                continue
            try:
                if sym not in data_cache:
                    intra = intraday_bars(sym, period="30d")
                    data_cache[sym] = (daily_bars(sym), intra, current_price(ibkr, sym, intra))
                daily, intra, price = data_cache[sym]
            except Exception as exc:
                log("entry_skip", symbol=sym, strategy=sid, reason=f"data error {exc!r}")
                continue
            if math.isnan(price) or price < cfg["min_price"]:
                log("entry_skip", symbol=sym, strategy=sid, reason=f"price {price} below min or missing")
                continue
            bars_1m = None
            if cfg.get("timeframe") == "1m":
                try:
                    if (sym, "1m") not in data_cache:
                        data_cache[(sym, "1m")] = intraday_bars(sym, period="5d", interval="1m")  # a few days so EMAs are warmed up
                    bars_1m = data_cache[(sym, "1m")]
                except Exception as exc:
                    log("entry_skip", symbol=sym, strategy=sid, reason=f"1-minute data error {exc!r}")
                    continue
            if bars_1m is not None and not bars_1m.empty:
                price = current_price(ibkr, sym, bars_1m)  # freshest price for a 1-minute decision
            res = st.evaluate(cfg, daily, intra, price, today, rules, now_t, symbol=sym, bars_1m=bars_1m)
            log("evaluate", symbol=sym, strategy=sid, passed=bool(res["pass"]), reasons=res["reasons"], metrics=res["metrics"])
            if not res["pass"]:
                continue

            stop = float(res["metrics"]["stop"])
            side = res["metrics"].get("side", "long")
            size = position_size(price, stop, portfolio, risk_pct,
                                 float(rules["risk"]["max_position_size_pct_of_portfolio"]),
                                 env_float("MAX_TRADE_SIZE_USD", 2500))
            if size < 1:
                log("entry_skip", symbol=sym, strategy=sid, reason="size < 1", price=price, stop=stop)
                continue

            d = -1 if side == "short" else 1
            limit = None
            if cfg.get("max_slip_R"):  # cap slippage: limit = decision price + a fraction of the risk
                limit = _round_price(price + d * cfg["max_slip_R"] * abs(price - stop))
            result, out = run_trade(sym, "SELL" if d < 0 else "BUY", size, stop_price=stop, strategy=sid, limit=limit)
            buys += 1  # count attempts too: a timed-out order may still fill
            s_buys += 1
            held.add(sym)
            ibkr.ib.sleep(1)
            qty = ibkr.position_qty(sym) * d
            if qty <= 0:
                log("entry_unfilled", symbol=sym, strategy=sid, side=side, limit=limit, result=result, output=out[-500:])
                continue
            fill = float(result["fill_price"]) if result and result.get("fill_price") else price
            if (fill - stop) * d <= 0:
                # filled at or beyond the stop (price moved during the order): the setup is gone; flatten now
                out_res, _ = run_trade(sym, "BUY" if d < 0 else "SELL", qty, strategy=sid)
                log("entry_invalid", symbol=sym, strategy=sid, side=side, fill=fill, stop=stop,
                    closed=bool(out_res and out_res.get("filled")))
                safe_notify(f"ENTRY CANCELLED {sym}", f"filled ${fill:.2f} beyond the stop ${stop:.2f}; closed right away", "high")
                continue
            t = ibkr.place_stop(sym, qty, stop, action="BUY" if d < 0 else "SELL")
            pos = new_position(sym, fill, qty, stop, t, strategy=sid, side=side,
                               exit_rules=None if cfg["type"] == "trend_join" else cfg["exit"])
            positions.append(pos)
            save_positions(positions)  # persist right away so a crash later this run can't orphan it
            log("entry", symbol=sym, strategy=sid, side=side, qty=qty, price=fill, stop=stop, R=pos["R"], stop_order_id=t.order.orderId)
            safe_notify(f"{'SHORT' if d < 0 else 'BUY'} {sym} · {cfg['name']}", f"@ ${fill:.2f}, stop ${stop:.2f}, qty {qty}")


# ---------------------------------------------------------------- main

def main() -> int:
    rules = load_rules()
    status = time_gate(now_et(), rules, entry_window(rules))
    if status in {"weekend", "too_early", "closed"}:
        print(f"{ts()} {status}: nothing to do")
        return 0
    if msg := check_paper_live_guard():
        log("abort", reason=msg)
        return 1
    if status == "ok" and PAUSE_PATH.exists():
        status = "manage_only"  # paused from the app: keep managing open trades, no new entries

    ibkr = None
    try:
        ibkr = connect()
        positions = load_positions()
        positions = reconcile(ibkr, positions)
        adopt_orphans(ibkr, positions, rules)
        if status != "force_close":
            manage(ibkr, positions, rules)
        save_positions(positions)

        if status == "force_close":
            save_positions(force_close(ibkr, positions))
            return 0
        if status == "manage_only":
            log("manage_only", open_positions=len(positions))
            return 0

        entry_scan(ibkr, positions, rules)
        save_positions(positions)
        log("cycle_done", status=status, open_positions=len(positions))
        return 0
    except Exception as exc:
        if type(exc).__name__ == "AccountLockError":
            log("account_lock", reason=str(exc))
            safe_notify("BOT STOPPED: wrong account", str(exc), "high")
            print(f"{ts()} {exc}")
            return 1
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (LOGS_DIR / "cycle_errors.log").open("a", encoding="utf-8") as f:
            f.write(f"--- {now_et().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
        safe_notify("Cycle CRASHED", str(exc)[:500], "high")
        print(f"{ts()} CRASH: {exc!r} (see logs/cycle_errors.log)")
        return 1
    finally:
        if ibkr is not None:
            ibkr.disconnect()


if __name__ == "__main__":
    sys.exit(main())
