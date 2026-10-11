"""Single-symbol dev tool: check the gate for one ticker and optionally buy it.

    python bot.py --symbol NVDA --check-only
    python bot.py --symbol NVDA
"""
from __future__ import annotations

import argparse
import sys

import strategy
from src.common import (check_paper_live_guard, ensure_trades_csv, env_float, env_int, env_str, load_rules,
                        read_trades, todays_buy_count, ts)
from src.executor import run_trade
from src.ibkr_client import IBKRClient


def say(msg: str) -> None:
    print(f"{ts()} {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    symbol = args.symbol.upper()

    if msg := check_paper_live_guard():
        sys.exit(msg)

    ensure_trades_csv()
    max_trades = env_int("MAX_TRADES_PER_DAY", 5)
    count = todays_buy_count()
    if count >= max_trades:
        say(f"daily trade cap reached ({count}/{max_trades}); nothing to do")
        return 0

    try:
        ibkr = IBKRClient(env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), env_int("IBKR_CLIENT_ID", 2))
    except Exception as exc:
        say(f"CONNECT FAILED: {exc!r}")
        return 1
    try:
        result = strategy.evaluate(symbol, ibkr.ib)
        say(f"evaluate({symbol}) -> {result}")
        if args.check_only:
            say("check-only: no order placed")
            return 0
        if not result["pass"]:
            say("not taking trade: " + "; ".join(result["reasons"]))
            return 0
    finally:
        ibkr.disconnect()

    risk = load_rules()["risk"]
    budget = min(env_float("MAX_TRADE_SIZE_USD", 2500),
                 env_float("PORTFOLIO_VALUE_USD", 25000) * float(risk["max_position_size_pct_of_portfolio"]) / 100)
    quantity = int(budget / result["price"])
    if quantity < 1:
        say(f"position too small (budget ${budget:.0f}, price ${result['price']:.2f})")
        return 0

    say(f"BUY {quantity} {symbol} @ ~${result['price']:.2f}")
    trade_result, output = run_trade(symbol, "BUY", quantity)
    for line in output.splitlines():
        say(f"  trade.py | {line}")
    if trade_result is None:
        say("FAILED: trade.py did not report a result")
        return 1

    last = read_trades()[-1] if read_trades() else {}
    if trade_result["status"] == "Filled":
        say(f"SUCCESS: {last.get('size')} {symbol} filled @ {last.get('fill_price')} (order {last.get('order_id')})")
        say("NOTE: bot.py places no stop. Manage/close it in TWS or with close_one.py " + symbol)
        return 0
    say(f"NOT FILLED: status {trade_result['status']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
