"""Order executor. Runs as its own process with IBKR_EXEC_CLIENT_ID so it never fights the
orchestrator (bot.py / cycle.py) for the TWS connection.

Prints a final line `RESULT {json}` that the caller parses.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.common import append_trade, check_paper_live_guard, env_int, env_str, now_et
from src.ibkr_client import DEAD, IBKRClient


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"])
    ap.add_argument("--size", required=True, type=int)
    ap.add_argument("--stop-price", type=float, default=None, help="initial stop, logged for R calculations")
    ap.add_argument("--strategy", default="", help="which strategy opened/closed this trade")
    args = ap.parse_args()
    side = args.side.upper()

    if msg := check_paper_live_guard():
        print(msg)
        return 1
    if args.size < 1:
        print("size must be >= 1")
        return 1

    try:
        ibkr = IBKRClient(env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), env_int("IBKR_EXEC_CLIENT_ID", 3))
    except Exception as exc:
        print(f"CONNECT FAILED: {exc!r}")
        return 1

    try:
        trade = ibkr.place_order(args.symbol, side, args.size)
        st = trade.orderStatus
        result = {"symbol": args.symbol, "side": side, "size": args.size, "status": st.status,
                  "filled": int(st.filled), "fill_price": float(st.avgFillPrice or 0), "order_id": trade.order.orderId}
        if st.status in DEAD:
            for entry in trade.log:
                print(f"  log: {entry.status} {entry.message} {entry.errorCode}")
            print("RESULT " + json.dumps(result))
            return 2
        append_trade({
            "timestamp_iso": now_et().isoformat(timespec="seconds"),  # ET, so "today" checks line up
            "symbol": args.symbol, "side": side, "size": result["filled"] or args.size,
            "fill_price": result["fill_price"], "order_id": result["order_id"], "status": st.status,
            "stop_price": "" if args.stop_price is None else round(args.stop_price, 4),
            "strategy": args.strategy,
        })
        print("RESULT " + json.dumps(result))
        return 0
    except Exception as exc:
        print(f"ORDER FAILED: {exc!r}")
        return 1
    finally:
        ibkr.disconnect()


if __name__ == "__main__":
    sys.exit(main())
