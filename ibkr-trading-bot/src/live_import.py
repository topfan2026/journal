"""Your LIVE account's trade history: import IBKR exports, sync via the Flex Web Service, and turn
the fills into round-trip trades for the app's charts. Completely separate from the bot's
paper trades (trades.csv).

Accepted files:
- IBKR Activity Statement CSV (Client Portal > Performance & Reports > Statements > Activity, CSV)
- IBKR Flex Query export, CSV or XML (Trades section)
- Any simple CSV with date/time, symbol, side (or signed quantity), quantity and price columns

Read-only: nothing here can place orders.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET_XML
from collections import defaultdict
from datetime import datetime

from src.common import ET, PROJECT_DIR, env_str, now_et

LIVE_PATH = PROJECT_DIR / "live_trades.csv"
FIELDS = ["id", "time", "symbol", "asset", "side", "qty", "price", "commission", "realized", "mult",
          "account", "open_close", "source", "currency"]
FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


# ------------------------------------------------------------------ parsing helpers

def _f(x, default=None):
    if x is None:
        return default
    s = str(x).strip().replace(",", "").replace("$", "")
    if s in ("", "--", "-", "N/A"):
        return default
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return default


def parse_time(text: str, extra: str = "") -> str | None:
    """IBKR & common formats -> ISO with the New York offset."""
    s = f"{text} {extra}".strip().strip('"').replace(";", " ").replace(",", " ")
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H%M%S", "%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M:%S",
                "%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%d-%b-%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=ET).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s)
        return (dt if dt.tzinfo else dt.replace(tzinfo=ET)).astimezone(ET).isoformat(timespec="seconds")
    except ValueError:
        return None


def _fill(time_iso, symbol, side, qty, price, commission=0.0, realized=None, mult=1.0, asset="STK",
          account="", open_close="", exec_id="", source="", currency="") -> dict | None:
    if not time_iso or not symbol or not qty or price is None:
        return None
    side = side.upper()
    side = "BUY" if side.startswith(("B", "BOT")) else "SELL" if side.startswith(("S", "SLD")) else side
    if side not in ("BUY", "SELL"):
        return None
    key = exec_id or hashlib.sha1(f"{time_iso}|{symbol}|{side}|{abs(qty)}|{price}".encode()).hexdigest()[:16]
    return {"id": str(key), "time": time_iso, "symbol": symbol.strip(), "asset": asset or "STK", "side": side,
            "qty": abs(float(qty)), "price": float(price), "commission": abs(float(commission or 0)),
            "realized": "" if realized is None else float(realized), "mult": float(mult or 1),
            "account": account or "", "open_close": open_close or "", "source": source,
            "currency": (currency or "").upper()}


def _pick(row: dict, *names):
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        if n.lower() in low and str(low[n.lower()]).strip() != "":
            return low[n.lower()]
    return None


def _from_mapping(row: dict, source: str) -> dict | None:
    """One trade row (Flex CSV/XML or a generic CSV) -> normalized fill."""
    t = _pick(row, "DateTime", "Date/Time", "TradeDateTime", "Datetime", "Time", "Date")
    extra = ""
    if _pick(row, "DateTime", "Date/Time", "TradeDateTime", "Datetime") is None:
        d, tm = _pick(row, "TradeDate", "Date"), _pick(row, "TradeTime", "Time")
        if d and tm and d != tm:
            t, extra = d, tm
    qty = _f(_pick(row, "Quantity", "Qty", "Shares", "Filled"))
    side = _pick(row, "Buy/Sell", "BuySell", "Side", "Action", "Type")
    if qty is None:
        return None
    if not side:
        side = "BUY" if qty > 0 else "SELL"
    price = _f(_pick(row, "TradePrice", "T. Price", "Price", "Fill Price", "Avg Price", "AvgPrice", "Execution Price"))
    realized = _f(_pick(row, "FifoPnlRealized", "Realized P/L", "RealizedPnl", "Realized P&L", "Realized"))
    comm = _f(_pick(row, "IBCommission", "Comm/Fee", "Commission", "Commissions", "Fees"), 0.0)
    asset = _pick(row, "AssetClass", "Asset Category", "AssetCategory", "SecType") or "STK"
    oc = _pick(row, "Open/CloseIndicator", "OpenCloseIndicator", "Code") or ""
    return _fill(parse_time(str(t or ""), str(extra or "")), _pick(row, "Symbol", "Ticker", "UnderlyingSymbol") or "",
                 str(side), qty, price, comm, realized, _f(_pick(row, "Multiplier"), 1.0), asset,
                 _pick(row, "ClientAccountID", "AccountId", "Account") or "", str(oc),
                 _pick(row, "TradeID", "IBExecID", "ExecID", "TransactionID") or "", source,
                 _pick(row, "CurrencyPrimary", "Currency") or "")


def parse_activity_statement(text: str) -> list[dict]:
    """IBKR Activity Statement CSV: sections of 'Trades,Header,...' / 'Trades,Data,Order,...' rows."""
    fills, header, account = [], None, ""
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 4 and row[0] == "Account Information" and row[1] == "Data" and row[2] == "Account":
            account = row[3].split()[0]  # "U1234567 (Custom)" -> "U1234567"
        if len(row) < 3 or row[0] != "Trades":
            continue
        if row[1] == "Header":
            header = row[2:]
        elif row[1] == "Data" and header:
            rec = dict(zip(header, row[2:]))
            if rec.get("DataDiscriminator", "Order") not in ("Order", "Trade"):
                continue
            f = _from_mapping(rec, "activity_statement")
            if f and not f["account"]:
                f["account"] = account
            if f:
                fills.append(f)
    return fills


def parse_flex_xml(text: str) -> list[dict]:
    root = ET_XML.fromstring(text)
    fills = []
    for el in root.iter("Trade"):
        a = dict(el.attrib)
        if a.get("levelOfDetail", "EXECUTION").upper() not in ("EXECUTION", ""):
            continue  # skip ORDER/SUMMARY roll-ups so fills aren't double counted
        f = _from_mapping(a, "flex")
        if f:
            fills.append(f)
    return fills


def parse_generic_csv(text: str) -> list[dict]:
    """Flex CSV or any CSV with a header row. Re-detects headers (Flex CSVs can hold several sections)."""
    fills, header = [], None
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(c.strip() for c in row):
            continue
        if row[0] in ("HEADER", "DATA") and len(row) > 2:  # Flex 'include header and trailer records'
            row = row[2:]
        cells = [c.strip().lower() for c in row]
        if "symbol" in cells and any(c in cells for c in ("quantity", "qty", "shares")):
            header = row
            continue
        if header:
            f = _from_mapping(dict(zip(header, row)), "csv")
            if f:
                fills.append(f)
    return fills


def parse_any(text: str) -> list[dict]:
    t = text.lstrip("﻿").strip()
    if t.startswith("<"):
        return parse_flex_xml(t)
    if t.startswith("Statement,") or "\nTrades,Header," in t or t.startswith("Trades,Header,"):
        return parse_activity_statement(t)
    return parse_generic_csv(t)


# ------------------------------------------------------------------ storage

def load_fills() -> list[dict]:
    if not LIVE_PATH.exists():
        return []
    with LIVE_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["qty"], r["price"], r["commission"], r["mult"] = (float(r["qty"]), float(r["price"]),
                                                             float(r["commission"] or 0), float(r["mult"] or 1))
        r["realized"] = float(r["realized"]) if r["realized"] not in ("", None) else None
        r["currency"] = r.get("currency") or ""
        r["account"] = r.get("account") or ""
    return rows


def merge_fills(new: list[dict]) -> dict:
    existing = load_fills()
    seen = {r["id"] for r in existing}
    added = [f for f in new if f["id"] not in seen and not seen.add(f["id"])]
    rows = sorted(existing + added, key=lambda r: r["time"])
    tmp = LIVE_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "realized": "" if r.get("realized") in (None, "") else r["realized"]})
    tmp.replace(LIVE_PATH)
    return {"found": len(new), "added": len(added), "total": len(rows)}


def import_text(text: str) -> dict:
    fills = parse_any(text)
    if not fills:
        return {"ok": False, "message": "No trades found in that file. Use an IBKR Activity Statement or Flex Query "
                                        "export (CSV or XML) that includes the Trades section."}
    res = merge_fills(fills)
    return {"ok": True, "message": f"Imported {res['added']} new fills ({res['found'] - res['added']} already there). "
                                   f"{res['total']} fills stored.", **res}


def clear() -> None:
    LIVE_PATH.unlink(missing_ok=True)


# ------------------------------------------------------------------ Flex Web Service sync

def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ibkr-trading-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def flex_configured() -> bool:
    return bool(env_str("FLEX_TOKEN") and env_str("FLEX_QUERY_ID"))


def flex_sync() -> dict:
    """Ask IBKR to generate the Flex statement, wait for it, import its trades."""
    token, qid = env_str("FLEX_TOKEN"), env_str("FLEX_QUERY_ID")
    if not (token and qid):
        return {"ok": False, "message": "Add your Flex token and query ID first."}
    q = urllib.parse.urlencode
    resp = ET_XML.fromstring(_http(f"{FLEX_BASE}/SendRequest?{q({'t': token, 'q': qid, 'v': 3})}"))
    if (resp.findtext("Status") or "").lower() != "success":
        return {"ok": False, "message": f"IBKR refused the request: {resp.findtext('ErrorMessage') or 'unknown error'} "
                                        f"(code {resp.findtext('ErrorCode')}). Check the token and query ID."}
    ref, url = resp.findtext("ReferenceCode"), resp.findtext("Url") or f"{FLEX_BASE}/GetStatement"
    for _ in range(12):  # the statement can take a little while to generate
        text = _http(f"{url}?{q({'t': token, 'q': ref, 'v': 3})}")
        if "<FlexStatementResponse" in text[:300] and "1019" in text:  # 1019 = generation in progress
            time.sleep(5)
            continue
        if "<FlexStatementResponse" in text[:300]:
            err = ET_XML.fromstring(text)
            return {"ok": False, "message": f"IBKR: {err.findtext('ErrorMessage')} (code {err.findtext('ErrorCode')})"}
        result = import_text(text)
        result["message"] = "Synced from IBKR. " + result["message"]
        return result
    return {"ok": False, "message": "IBKR is still generating the statement; try Sync again in a minute."}


# ------------------------------------------------------------------ fills -> round-trip trades

def round_trips(fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """Group fills into trades: a trade runs from flat to flat (long or short). Uses IBKR's own
    realized P&L (net of commissions) when the export has it. Returns (closed_trades, open_positions)."""
    by_sym: dict[tuple, list[dict]] = defaultdict(list)
    for f in sorted(fills, key=lambda r: r["time"]):
        # positions in different accounts are separate, never netted against each other
        by_sym[(f.get("account", ""), f["symbol"], f.get("asset", "STK"))].append(f)

    trades, still_open = [], []
    for (account, sym, asset), rows in by_sym.items():
        currency = next((r.get("currency") for r in rows if r.get("currency")), "")
        pos = 0.0
        lots: list[list] = []  # [signed qty, price]
        ep = None

        def start(f, q, sign):
            return {"symbol": sym, "asset": asset, "account": account, "currency": currency,
                    "side": "long" if sign > 0 else "short", "entry_time": f["time"],
                    "open_qty": 0.0, "open_value": 0.0, "close_qty": 0.0, "close_value": 0.0, "pnl": 0.0,
                    "mult": f["mult"], "fills": 0}

        for f in rows:
            sign = 1 if f["side"] == "BUY" else -1
            q, px, mult = f["qty"], f["price"], f["mult"]
            realized = f["realized"]
            closing_hint = "C" in str(f.get("open_close", "")).upper().split(";") or (realized not in (None, 0.0))
            if pos == 0 and closing_hint and realized is not None:
                # closes a position opened before this data starts: we only know IBKR's realized P&L
                trades.append({"symbol": sym, "asset": asset, "account": account, "currency": currency,
                               "side": "long" if sign < 0 else "short", "qty": q,
                               "buy": None, "sell": px, "pnl": realized, "pnl_pct": None, "R": None,
                               "entry_time": f["time"], "exit_time": f["time"], "hold_min": None, "partial_history": True})
                continue
            if pos == 0 or (pos > 0) == (sign > 0):  # opening / adding
                if pos == 0:
                    ep = start(f, q, sign)
                lots.append([sign * q, px])
                pos += sign * q
                ep["open_qty"] += q
                ep["open_value"] += q * px
                ep["fills"] += 1
                if realized is None:
                    ep["pnl"] -= f["commission"]
                continue
            # reducing (and maybe flipping)
            close_q = min(q, abs(pos))
            computed = 0.0
            left = close_q
            while left > 1e-9 and lots:
                lot_q, lot_px = lots[0]
                take = min(left, abs(lot_q))
                computed += (px - lot_px) * take * (1 if lot_q > 0 else -1) * mult
                lots[0][0] -= take if lot_q > 0 else -take
                if abs(lots[0][0]) < 1e-9:
                    lots.pop(0)
                left -= take
            ep["pnl"] += realized if realized is not None else computed - f["commission"] * (close_q / q)
            ep["close_qty"] += close_q
            ep["close_value"] += close_q * px
            ep["fills"] += 1
            pos += sign * close_q
            if abs(pos) < 1e-9:
                pos = 0.0
                trades.append(_finish(ep, f["time"]))
                ep = None
            rem = q - close_q
            if rem > 1e-9:  # flipped direction
                ep = start(f, rem, sign)
                lots = [[sign * rem, px]]
                pos = sign * rem
                ep["open_qty"], ep["open_value"], ep["fills"] = rem, rem * px, 1
        if ep and pos:
            still_open.append({"symbol": sym, "asset": asset, "account": account, "side": ep["side"], "qty": abs(pos),
                               "avg": ep["open_value"] / ep["open_qty"], "since": ep["entry_time"]})
    trades.sort(key=lambda t: t["exit_time"])
    return trades, still_open


def _finish(ep: dict, exit_time: str) -> dict:
    entry_avg = ep["open_value"] / ep["open_qty"]
    exit_avg = ep["close_value"] / ep["close_qty"] if ep["close_qty"] else entry_avg
    basis = entry_avg * ep["open_qty"] * ep["mult"]
    hold = (datetime.fromisoformat(exit_time) - datetime.fromisoformat(ep["entry_time"])).total_seconds() / 60
    long = ep["side"] == "long"
    return {"symbol": ep["symbol"], "asset": ep["asset"], "account": ep["account"], "currency": ep["currency"],
            "side": ep["side"], "qty": ep["open_qty"],
            "buy": entry_avg if long else exit_avg, "sell": exit_avg if long else entry_avg,
            "pnl": ep["pnl"], "pnl_pct": ep["pnl"] / basis * 100 if basis else None, "R": None,
            "entry_time": ep["entry_time"], "exit_time": exit_time, "hold_min": round(hold, 1),
            "partial_history": False}


def summary() -> dict:
    fills = load_fills()
    trades, still_open = round_trips(fills)
    return {"closed": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()} for t in trades[-5000:]],
            "open": still_open, "fills": len(fills),
            "first": fills[0]["time"][:10] if fills else None, "last": fills[-1]["time"][:10] if fills else None,
            "accounts": sorted({f["account"] for f in fills if f.get("account")}),
            "accounts_detail": [{"account": a or "(unknown)", "key": a,
                                 "currency": ",".join(sorted({f["currency"] for f in fills if f["account"] == a and f["currency"]})) or "",
                                 "fills": sum(1 for f in fills if f["account"] == a)}
                                for a in sorted({f["account"] for f in fills})],
            "commissions": round(sum(f["commission"] for f in fills), 2),
            "flex_configured": flex_configured(),
            "updated": datetime.fromtimestamp(LIVE_PATH.stat().st_mtime, ET).strftime("%Y-%m-%d %H:%M ET")
            if LIVE_PATH.exists() else None,
            "now": now_et().isoformat(timespec="seconds")}
