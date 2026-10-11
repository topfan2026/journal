"""Single-symbol dev gate used by bot.py: position dedupe + entry time window only.

The full D1-D3 / I1-I3 filters live in src/filters.py and run inside cycle.py.
"""
from __future__ import annotations

import math
from datetime import time

from ib_async import IB, Stock

from src.common import LOGS_DIR, append_jsonl, load_rules, now_et


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _log(result: dict) -> dict:
    append_jsonl(LOGS_DIR / "safety_log.jsonl", result)
    return result


def evaluate(symbol: str, ib: IB) -> dict:
    for p in ib.positions():
        if p.contract.symbol == symbol and p.position > 0:
            return _log({"symbol": symbol, "pass": False, "reasons": ["already in position"], "price": 0.0})

    tf = load_rules()["time_filter"]
    start, end = _hhmm(tf["earliest_entry_et"]), _hhmm(tf["latest_entry_et"])
    now = now_et()
    if now.weekday() >= 5 or not (start <= now.time() <= end):
        return _log({"symbol": symbol, "pass": False,
                     "reasons": [f"outside entry window {tf['earliest_entry_et']}-{tf['latest_entry_et']} ET"], "price": 0.0})

    [contract] = ib.qualifyContracts(Stock(symbol, "SMART", "USD"))
    [ticker] = ib.reqTickers(contract)
    price = next((float(v) for v in (ticker.marketPrice(), ticker.last, ticker.close)
                  if v is not None and not math.isnan(v) and v > 0), 0.0)
    if price <= 0:
        return _log({"symbol": symbol, "pass": False, "reasons": ["no market price from IBKR"], "price": 0.0})
    return _log({"symbol": symbol, "pass": bool(True), "reasons": ["time gate ok", "no existing position"], "price": price})
