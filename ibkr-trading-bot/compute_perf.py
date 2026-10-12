"""Daily performance: JSON to stdout, Telegram summary, and dashboard/index.html.

Run after the close (scheduled 16:05 ET). Safe any time of day; never modifies trades.csv.
"""
from __future__ import annotations

import html
import json
import math
import sys
from collections import defaultdict, deque
from datetime import datetime

from src.common import DASHBOARD_DIR, SAFETY_LOG_PATH, load_positions, now_et, read_trades, to_py
from src.notify import notify

BUCKETS = [("≤ -2R", -math.inf, -2), ("-2R…-1R", -2, -1), ("-1R…0R", -1, 0), ("0R…+1R", 0, 1),
           ("+1R…+2R", 1, 2), ("+2R…+3R", 2, 3), ("> +3R", 3, math.inf)]


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def pair_trades(rows: list[dict]) -> list[dict]:
    """FIFO-match SELL shares against earlier BUY lots per symbol (handles partial exits)."""
    lots: dict[str, deque] = defaultdict(deque)
    closed = []
    for r in rows:
        qty, px = int(_f(r.get("size"))), _f(r.get("fill_price"))
        if qty <= 0 or px <= 0:
            continue
        sym = r["symbol"]
        if r["side"] == "BUY":
            lots[sym].append({"qty": qty, "price": px, "time": r["timestamp_iso"], "stop": _f(r.get("stop_price"), 0) or None,
                              "strategy": r.get("strategy") or "trend_join_long"})
            continue
        while qty > 0 and lots[sym]:
            lot = lots[sym][0]
            take = min(qty, lot["qty"])
            stop = lot["stop"] if lot["stop"] else lot["price"] * 0.99  # proxy when no stop was logged
            risk = lot["price"] - stop
            pnl = (px - lot["price"]) * take
            hold = (datetime.fromisoformat(r["timestamp_iso"]) - datetime.fromisoformat(lot["time"])).total_seconds() / 60
            closed.append({"symbol": sym, "qty": take, "buy": lot["price"], "sell": px, "stop": stop,
                           "pnl": pnl, "pnl_pct": (px / lot["price"] - 1) * 100,
                           "R": (px - lot["price"]) / risk if risk > 0 else 0.0,
                           "hold_min": round(hold, 1), "exit_time": r["timestamp_iso"], "entry_time": lot["time"],
                           "strategy": lot["strategy"]})
            lot["qty"] -= take
            qty -= take
            if lot["qty"] == 0:
                lots[sym].popleft()
    return closed


def group_trades(pieces: list[dict]) -> list[dict]:
    """Merge the FIFO pieces of one entry (partial exit + final exit) back into ONE trade, so
    win rate and averages count trades rather than exit fills."""
    groups: dict[tuple, list[dict]] = {}
    for c in pieces:
        groups.setdefault((c["symbol"], c["entry_time"], c["buy"], c.get("strategy", "")), []).append(c)
    trades = []
    for (sym, entry_time, buy, strategy), parts in groups.items():
        qty = sum(p["qty"] for p in parts)
        pnl = sum(p["pnl"] for p in parts)
        sell = sum(p["sell"] * p["qty"] for p in parts) / qty
        risk = buy - parts[0]["stop"]
        trades.append({"symbol": sym, "qty": qty, "buy": buy, "sell": sell, "stop": parts[0]["stop"],
                       "pnl": pnl, "pnl_pct": (sell / buy - 1) * 100,
                       "R": pnl / (risk * qty) if risk > 0 else 0.0,
                       "hold_min": max(p["hold_min"] for p in parts), "exits": len(parts), "strategy": strategy,
                       "entry_time": entry_time, "exit_time": max(p["exit_time"] for p in parts)})
    return sorted(trades, key=lambda t: t["exit_time"])


def aggregate(closed: list[dict]) -> dict:
    wins = [c for c in closed if c["pnl"] > 0]
    losses = [c for c in closed if c["pnl"] <= 0]
    gross_w, gross_l = sum(c["pnl"] for c in wins), sum(c["pnl"] for c in losses)
    best = max(closed, key=lambda c: c["pnl"], default=None)
    worst = min(closed, key=lambda c: c["pnl"], default=None)
    pf = "n/a" if not closed else ("inf" if gross_l == 0 else round(gross_w / abs(gross_l), 2))
    return {
        "total_trades": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "gross_pnl_usd": round(gross_w + gross_l, 2),
        "largest_winner": {"symbol": best["symbol"], "pnl": round(best["pnl"], 2)} if best else None,
        "largest_loser": {"symbol": worst["symbol"], "pnl": round(worst["pnl"], 2)} if worst else None,
        "avg_winner": round(gross_w / len(wins), 2) if wins else 0.0,
        "avg_loser": round(gross_l / len(losses), 2) if losses else 0.0,
        "profit_factor": pf,
        "avg_R": round(sum(c["R"] for c in closed) / len(closed), 2) if closed else 0.0,
    }


def histogram(closed: list[dict]) -> list[tuple[str, int]]:
    out = []
    for label, lo, hi in BUCKETS:
        out.append((label, sum(1 for c in closed if lo < c["R"] <= hi)))
    return out


def last_cycle() -> str:
    if not SAFETY_LOG_PATH.exists():
        return "no cycle data yet"
    lines = SAFETY_LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return "no cycle data yet"
    try:
        rec = json.loads(lines[-1])
        return f"{rec.get('ts', '?')} — {rec.get('event', '?')}"
    except json.JSONDecodeError:
        return "unreadable"


def open_position_rows() -> list[dict]:
    rows = []
    for p in load_positions():
        price = None
        try:
            from src.marketdata import intraday_bars
            bars = intraday_bars(p["symbol"], period="1d")
            price = float(bars["Close"].iloc[-1]) if not bars.empty else None
        except Exception:
            pass
        R = p.get("R") or (p["entry_price"] - p["initial_stop"])
        rows.append({"symbol": p["symbol"], "qty": p["qty"], "entry": p["entry_price"], "stop": p["stop"],
                     "uR": round((price - p["entry_price"]) / R, 2) if price and R > 0 else None})
    return rows


def render_html(today: str, agg: dict, all_closed: list[dict], open_rows: list[dict]) -> str:
    e = html.escape
    hist = histogram(all_closed)
    peak = max((n for _, n in hist), default=0) or 1
    bars = "".join(
        f'<div class="d-flex align-items-center mb-1"><div style="width:90px" class="small">{e(lbl)}</div>'
        f'<div class="flex-grow-1"><div class="{"bg-danger" if i < 3 else "bg-success"}" '
        f'style="height:18px;width:{n / peak * 100:.0f}%;min-width:{2 if n else 0}px"></div></div>'
        f'<div style="width:30px" class="text-end small">{n}</div></div>'
        for i, (lbl, n) in enumerate(hist))
    pos_rows = "".join(
        f"<tr><td>{e(r['symbol'])}</td><td>{r['qty']}</td><td>{r['entry']:.2f}</td><td>{r['stop']:.2f}</td>"
        f"<td>{'n/a' if r['uR'] is None else format(r['uR'], '+.2f') + 'R'}</td></tr>" for r in open_rows
    ) or '<tr><td colspan="5" class="text-muted">No open positions</td></tr>'
    recent = "".join(
        f"<tr><td>{e(c['exit_time'][:16])}</td><td>{e(c['symbol'])}</td><td>{c['qty']}</td><td>{c['buy']:.2f}</td>"
        f"<td>{c['sell']:.2f}</td><td>${c['pnl']:+.2f}</td>"
        f"<td class=\"{'text-success' if c['R'] > 0 else 'text-danger'} fw-bold\">{c['R']:+.2f}R</td></tr>"
        for c in reversed(all_closed[-20:])
    ) or '<tr><td colspan="7" class="text-muted">No closed trades yet</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>IBKR Bot Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body class="bg-light"><div class="container py-3">
<div class="alert alert-dark d-flex justify-content-between flex-wrap">
<strong>Bot Status: ACTIVE</strong><span>Last cycle: {e(last_cycle())}</span>
<span>Generated {e(now_et().strftime('%Y-%m-%d %H:%M ET'))}</span></div>
<div class="row g-3">
<div class="col-md-6"><div class="card h-100"><div class="card-header">Today's P&amp;L ({e(today)})</div><div class="card-body">
<h3 class="{'text-success' if agg['gross_pnl_usd'] >= 0 else 'text-danger'}">${agg['gross_pnl_usd']:+.2f}</h3>
<p class="mb-0">{agg['total_trades']} closed · {agg['wins']}W / {agg['losses']}L · win rate {agg['win_rate_pct']}% · PF {agg['profit_factor']} · avg {agg['avg_R']:+.2f}R</p>
</div></div></div>
<div class="col-md-6"><div class="card h-100"><div class="card-header">R-multiple histogram (all time)</div><div class="card-body">{bars}</div></div></div>
<div class="col-12"><div class="card"><div class="card-header">Open positions</div><div class="card-body p-0">
<table class="table table-sm mb-0"><thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Unrealized</th></tr></thead><tbody>{pos_rows}</tbody></table>
</div></div></div>
<div class="col-12"><div class="card"><div class="card-header">Recent closed trades (last 20)</div><div class="card-body p-0">
<table class="table table-sm mb-0"><thead><tr><th>Exit</th><th>Symbol</th><th>Qty</th><th>Buy</th><th>Sell</th><th>P&amp;L</th><th>R</th></tr></thead><tbody>{recent}</tbody></table>
</div></div></div></div></div></body></html>"""


def main() -> int:
    today = now_et().date().isoformat()
    all_closed = group_trades(pair_trades(read_trades()))
    todays = [c for c in all_closed if c["exit_time"].startswith(today)]
    agg = aggregate(todays)
    summary = to_py({"date": today, **agg})
    print(json.dumps(summary, indent=2))

    if todays:
        best, worst = agg["largest_winner"], agg["largest_loser"]
        body = (f"Trades: {agg['total_trades']} ({agg['wins']}W / {agg['losses']}L, {agg['win_rate_pct']}%)\n"
                f"P&L: ${agg['gross_pnl_usd']:+.2f}\nBest: {best['symbol']} ${best['pnl']:+.2f}\n"
                f"Worst: {worst['symbol']} ${worst['pnl']:+.2f}\nPF: {agg['profit_factor']}")
    else:
        body = "No closed trades today."
    notify(f"Daily Summary {today}", body)

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    (DASHBOARD_DIR / "index.html").write_text(render_html(today, agg, all_closed, open_position_rows()), encoding="utf-8")
    print(f"dashboard: {DASHBOARD_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
