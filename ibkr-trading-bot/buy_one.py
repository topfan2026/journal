"""Prompt 1: paper BUY 1 share of MU (wiring test). Does NOT close it; run close_one.py for that."""
import sys

from src.common import check_paper_live_guard, env_int, env_str
from src.ibkr_client import DEAD, IBKRClient

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "MU"


def main() -> int:
    if msg := check_paper_live_guard():
        print(msg)
        return 1
    try:
        ibkr = IBKRClient(env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497), client_id=10)
    except Exception as exc:
        print(f"CONNECT FAILED: {exc!r}. Is TWS running with the API enabled?")
        return 1
    try:
        trade = ibkr.place_order(SYMBOL, "BUY", 1)
        st = trade.orderStatus
        print("order id:", trade.order.orderId)
        print("fill price:", st.avgFillPrice if st.filled else "pending")
        print("status:", st.status)
        if st.status in DEAD:
            for entry in trade.log:
                print("  log:", entry.status, entry.message, entry.errorCode)
            return 1
        print(f"ORDERED: 1 share {SYMBOL}. Check TWS positions panel.")
        return 0
    finally:
        ibkr.disconnect()


if __name__ == "__main__":
    sys.exit(main())
