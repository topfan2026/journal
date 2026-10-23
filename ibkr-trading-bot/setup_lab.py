"""Setup Finder runner (started from the app): backtests the playbook + your strategies on recent days.

    python setup_lab.py --tickers SPY,NVDA,TSLA --days 20
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime

from src import setup_lab as lab
from src.common import load_rules


def progress(**kw) -> None:
    tmp = lab.PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kw), encoding="utf-8")
    tmp.replace(lab.PROGRESS_PATH)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=lab.DEFAULT_TICKERS)
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--no-mine", action="store_true", help="skip your own strategies")
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.replace(";", ",").split(",") if t.strip()][:25]
    days = max(3, min(58, args.days))
    started = datetime.now().isoformat(timespec="seconds")
    rules = load_rules()
    need_1m = any(c["cfg"].get("timeframe") == "1m" for c in lab.candidates(rules, tickers, not args.no_mine))

    from src.marketdata import daily_bars, intraday_bars

    def loader(sym):
        i1 = intraday_bars(sym, period="7d", interval="1m") if need_1m else None
        return daily_bars(sym), intraday_bars(sym, period="60d", interval="5m"), i1

    def report(done, total, note):
        progress(running=True, started=started, done=done, total=total, note=note)

    report(0, 1, "Starting")
    try:
        import os
        workers = max(1, min(4, (os.cpu_count() or 2) - 1))  # leave a core for TWS and the app
        res = lab.run(tickers, days, rules, loader, include_mine=not args.no_mine, report=report, workers=workers)
        if not res["days"]:
            progress(running=False, started=started, done=0, total=1,
                     note="No price data came back from Yahoo for these stocks (internet down, or wrong tickers?). "
                          "Nothing was tested; your previous results are kept.")
            print("no data")
            return 1
        lab.save_results(res)
        best = next((r for r in res["results"] if r["trades"]), None)
        note = f"Done: {len(res['results'])} setups on {len(tickers)} stocks over {res['days']} days"
        progress(running=False, started=started, finished=res["finished"], done=1, total=1, note=note)
        print(note + (f"; best: {best['name']} {best['avg_R']:+.2f}R/trade over {best['trades']} trades" if best else ""))
        return 0
    except Exception as exc:
        progress(running=False, started=started, done=0, total=1, note=f"Failed: {exc!r}"[:300])
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
