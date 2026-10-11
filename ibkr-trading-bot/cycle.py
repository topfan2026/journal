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

from src.common import (LOGS_DIR, SAFETY_LOG_PATH, WATCHLIST_PATH, append_jsonl, append_trade, check_paper_live_guard,
                        env_float, env_int, env_str, load_positions, load_rules, now_et, read_trades, read_watchlist,
                        save_positions, todays_buy_count, ts)

SESSION_START = time(10, 0)
SESSION_END = time(16, 0)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def time_gate(now: datetime, rules: dict) -> str:
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
    if t < _hhmm(tf["earliest_entry_et"]) or t > _hhmm(tf["latest_entry_et"]):
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

def stop_fills(ibkr, pos: dict) -> tuple[int, float]:
    """Shares and avg price filled on this position's stop order. Matches by order id / permId,
    never by quantity (quantity matching gives false stop-outs after a partial)."""
    since = datetime.now().astimezone() - timedelta(hours=8)
    shares, notional = 0.0, 0.0
    for f in ibkr.ib.fills():
        ex = f.execution
        if f.contract.symbol != pos["symbol"] or ex.side != "SLD":
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
        sym = pos["symbol"]
        held = ibkr.position_qty(sym)
        filled, px = stop_fills(ibkr, pos)
        if filled and held <= 0:
            pnl = (px - pos["entry_price"]) * filled
            append_trade({"timestamp_iso": now_et().isoformat(timespec="seconds"), "symbol": sym, "side": "SELL",
                          "size": filled, "fill_price": round(px, 4), "order_id": pos["stop_order_id"], "status": "StopFilled"})
            log("stopped_out", symbol=sym, qty=filled, exit=px, pnl=pnl)
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
            ibkr.modify_stop(sym, pos.get("stop_order_id"), held, pos["stop"])
        keep.append(pos)
    return keep


def adopt_orphans(ibkr, positions: list[dict], rules: dict) -> None:
    """A BUY the bot logged today that IBKR holds but state doesn't know about (e.g. trade.py
    timed out before the fill came back). Give it a stop instead of leaving it naked."""
    from src.filters import initial_stop
    from src.marketdata import intraday_bars
    from src.filters import _rth, _day

    known = {p["symbol"] for p in positions}
    today = now_et().date().isoformat()
    bought = {r["symbol"]: r for r in read_trades() if r["side"] == "BUY" and r["timestamp_iso"].startswith(today)}
    for sym, row in bought.items():
        if sym in known:
            continue
        qty = ibkr.position_qty(sym)
        if qty <= 0:
            continue
        entry = float(row.get("fill_price") or 0) or current_price(ibkr, sym)
        stop = float(row["stop_price"]) if row.get("stop_price") else None
        if stop is None:
            bars = _day(_rth(intraday_bars(sym, period="1d")), now_et().date())
            stop = initial_stop(float(bars["Low"].min()), rules["exit"]["initial_stop_rule"])
        t = ibkr.place_stop(sym, qty, stop)
        positions.append(new_position(sym, entry, qty, stop, t))
        log("orphan_adopted", symbol=sym, qty=qty, entry=entry, stop=stop, stop_order_id=t.order.orderId)
        safe_notify(f"ADOPTED {sym}", f"{qty} sh had no stop; stop ${stop:.2f} placed", "high")


def new_position(sym: str, entry: float, qty: int, stop: float, stop_trade) -> dict:
    return {"symbol": sym, "entry_price": entry, "entry_time_iso": now_et().isoformat(timespec="seconds"),
            "qty": qty, "initial_stop": stop, "stop": stop, "stop_order_id": stop_trade.order.orderId,
            "stop_perm_id": stop_trade.order.permId, "state": "pre_breakeven", "partial_done": False,
            "R": entry - stop}


# ---------------------------------------------------------------- step 4: manage

def manage(ibkr, positions: list[dict], rules: dict) -> None:
    from src.executor import run_trade
    from src.filters import _rth, swing_lows
    from src.marketdata import intraday_bars

    ex = rules["exit"]
    for pos in positions:
        sym, entry, R = pos["symbol"], pos["entry_price"], pos["R"]
        bars = intraday_bars(sym, period="1d")
        price = current_price(ibkr, sym, bars)
        if math.isnan(price) or R <= 0:
            log("manage_skip", symbol=sym, reason="no price or bad R")
            continue

        # 0.75R partial first: checking 1R first (as the original prompt did) means a stock that
        # jumps straight past 1R never banks its partial.
        if not pos["partial_done"] and price >= entry + ex["partial_profit_trigger_R"] * R and pos["qty"] > 1:
            sell = min(pos["qty"] - 1, math.ceil(pos["qty"] * ex["partial_profit_fraction"]))
            remaining = pos["qty"] - sell
            # Shrink the stop BEFORE selling so it can never be larger than the position (which
            # would open a short if it triggered).
            ibkr.modify_stop(sym, pos["stop_order_id"], remaining, pos["stop"])
            result, out = run_trade(sym, "SELL", sell)
            if result and result.get("filled"):
                sold = int(result["filled"])
                pos["qty"] = pos["qty"] - sold
                pos["partial_done"] = True
                pos["state"] = "partial_done" if pos["state"] == "pre_breakeven" else pos["state"]
                log("partial", symbol=sym, sold=sold, price=result["fill_price"], remaining=pos["qty"])
                safe_notify(f"PARTIAL {sym}", f"sold {sold}/{sold + pos['qty']} @ ${result['fill_price']:.2f}")
            else:
                ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], pos["stop"])
                log("partial_failed", symbol=sym, output=out[-500:])

        if pos["state"] != "post_breakeven" and price >= entry + ex["breakeven_trigger_R"] * R and entry > pos["stop"]:
            t = ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], entry)
            pos.update(stop=entry, stop_order_id=t.order.orderId, stop_perm_id=t.order.permId, state="post_breakeven")
            log("breakeven", symbol=sym, new_stop=entry)
            safe_notify(f"BE {sym}", f"stop -> ${entry:.2f}")

        if pos["state"] == "post_breakeven" and bars is not None and not bars.empty:
            entry_time = datetime.fromisoformat(pos["entry_time_iso"])
            completed = _rth(bars).iloc[:-1]  # newest bar is still forming
            lows = [(t, low) for t, low in swing_lows(completed, 2, 2) if t >= entry_time]
            if lows:
                new_stop = round(lows[-1][1] - 0.01, 2)
                if pos["stop"] < new_stop < price:  # ratchet up only
                    old = pos["stop"]
                    t = ibkr.modify_stop(sym, pos["stop_order_id"], pos["qty"], new_stop)
                    pos.update(stop=new_stop, stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
                    log("trail", symbol=sym, old_stop=old, new_stop=new_stop)
                    safe_notify(f"TRAIL {sym}", f"stop ${old:.2f} -> ${new_stop:.2f}")


# ---------------------------------------------------------------- step 6: force close

def force_close(ibkr, positions: list[dict]) -> list[dict]:
    from src.executor import run_trade

    if positions:
        safe_notify("EOD Force Close", f"flattening {len(positions)} positions", "high")
    left = []
    for pos in positions:
        sym = pos["symbol"]
        ibkr.cancel(pos.get("stop_order_id"))
        qty = ibkr.position_qty(sym)
        if qty <= 0:
            log("force_close_nothing_held", symbol=sym)
            continue
        result, out = run_trade(sym, "SELL", qty)
        if result and result.get("status") == "Filled":
            log("force_closed", symbol=sym, qty=qty, price=result["fill_price"])
        else:
            # Put the protective stop back so nothing sits naked; next run retries the close.
            t = ibkr.place_stop(sym, qty, pos["stop"])
            pos.update(stop_order_id=t.order.orderId, stop_perm_id=t.order.permId)
            left.append(pos)
            log("force_close_failed", symbol=sym, output=out[-500:])
            safe_notify(f"FORCE CLOSE FAILED {sym}", "stop re-placed; will retry next cycle", "high")
    return left


# ---------------------------------------------------------------- step 8: entries

def entry_scan(ibkr, positions: list[dict], rules: dict) -> None:
    from src.executor import run_trade
    from src.filters import evaluate_filters, initial_stop, position_size
    from src.marketdata import daily_bars, intraday_bars

    max_trades = env_int("MAX_TRADES_PER_DAY", 5)
    max_open = int(rules["risk"]["max_concurrent_positions"])
    buys = todays_buy_count()
    if buys >= max_trades:
        log("entry_skip", reason=f"daily trade cap {buys}/{max_trades}")
        return
    if not WATCHLIST_PATH.exists() or datetime.fromtimestamp(WATCHLIST_PATH.stat().st_mtime, now_et().tzinfo).date() != now_et().date():
        log("entry_skip", reason="watchlist.txt missing or not from today; run morning_prefilter.py")
        return

    held = ibkr.held_symbols() | {p["symbol"] for p in positions}  # IBKR first: avoids double entries
    portfolio = env_float("PORTFOLIO_VALUE_USD", 25000)
    risk_pct = env_float("MAX_RISK_PER_TRADE_PCT", float(rules["risk"]["max_risk_per_trade_pct"]))
    min_price = float(rules["universe_filters"]["min_price_usd"])
    today = now_et().date()

    for sym in read_watchlist():
        if buys >= max_trades or len(positions) >= max_open:
            log("entry_skip", reason="trade or concurrent-position cap reached")
            break
        if sym in held:
            log("entry_skip", symbol=sym, reason="already held")
            continue
        try:
            daily, intra = daily_bars(sym), intraday_bars(sym, period="30d")
        except Exception as exc:
            log("entry_skip", symbol=sym, reason=f"data error {exc!r}")
            continue
        price = current_price(ibkr, sym, intra)
        if math.isnan(price) or price < min_price:
            log("entry_skip", symbol=sym, reason=f"price {price} below min or missing")
            continue
        res = evaluate_filters(daily, intra, price, today, rules)
        log("evaluate", symbol=sym, passed=bool(res["pass"]), reasons=res["reasons"], metrics=res["metrics"])
        if not res["pass"]:
            continue

        stop = initial_stop(res["metrics"]["low_of_day"], rules["exit"]["initial_stop_rule"])
        size = position_size(price, stop, portfolio, risk_pct,
                             float(rules["risk"]["max_position_size_pct_of_portfolio"]),
                             env_float("MAX_TRADE_SIZE_USD", 2500))
        if size < 1:
            log("entry_skip", symbol=sym, reason="size < 1", price=price, stop=stop)
            continue

        result, out = run_trade(sym, "BUY", size, stop_price=stop)
        buys += 1  # count attempts too: a timed-out order may still fill
        ibkr.ib.sleep(1)
        qty = ibkr.position_qty(sym)
        if qty <= 0:
            log("entry_unfilled", symbol=sym, result=result, output=out[-500:])
            continue
        fill = float(result["fill_price"]) if result and result.get("fill_price") else price
        t = ibkr.place_stop(sym, qty, stop)
        pos = new_position(sym, fill, qty, stop, t)
        positions.append(pos)
        held.add(sym)
        save_positions(positions)  # persist right away so a crash later this run can't orphan it
        log("entry", symbol=sym, qty=qty, price=fill, stop=stop, R=pos["R"], stop_order_id=t.order.orderId)
        safe_notify(f"BUY {sym}", f"@ ${fill:.2f}, stop ${stop:.2f}, qty {qty}")


# ---------------------------------------------------------------- main

def main() -> int:
    rules = load_rules()
    status = time_gate(now_et(), rules)
    if status in {"weekend", "too_early", "closed"}:
        print(f"{ts()} {status}: nothing to do")
        return 0
    if msg := check_paper_live_guard():
        log("abort", reason=msg)
        return 1

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
