"""Prompt 2: flatten the position buy_one.py opened."""
import sys

from src.common import check_paper_live_guard, env_int, env_str
from src.ibkr_client import DEAD, IBKRClient

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "MU"


def main() -> int:
    if msg := check_paper_live_guard():
        print(msg)
        return 1
    try:
        ibkr = IBKRClient(env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), client_id=11)
    except Exception as exc:
        print(f"CONNECT FAILED: {exc!r}")
        return 1
    try:
        qty = ibkr.position_qty(SYMBOL)
        if qty <= 0:
            print("NO POSITION TO CLOSE")
            return 0
        trade = ibkr.place_order(SYMBOL, "SELL", qty)
        st = trade.orderStatus
        print("sold quantity:", st.filled, "of", qty)
        print("fill price:", st.avgFillPrice if st.filled else "pending")
        print("status:", st.status)
        if st.status in DEAD:
            for entry in trade.log:
                print("  log:", entry.status, entry.message, entry.errorCode)
            return 1
        print("CLOSED: position flat. Verify in TWS.")
        return 0
    finally:
        ibkr.disconnect()


if __name__ == "__main__":
    sys.exit(main())
