"""Data for the app's trade chart: candles, indicators, key levels, entry/exit markers, the bot's
reasons for the trade, and ticker details. Prices come from yfinance (5-minute bars are kept for
about 60 days; older dates fall back to hourly, then daily bars)."""
from __future__ import annotations

import json
import math
import time as _time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from src.common import ET, SAFETY_LOG_PATH, read_trades
from src.filters import RTH_OPEN, _day, _rth
from src.marketdata import yahoo_symbol

_info_cache: dict[str, tuple[float, dict]] = {}


def _ts(t) -> int:
    """Chart time: the New York wall-clock time encoded as UTC, so the chart's axis reads in ET."""
    t = pd.Timestamp(t)
    t = t.tz_convert(ET) if t.tzinfo else t.tz_localize(ET)
    return int((t.tz_localize(None) - pd.Timestamp("1970-01-01")).total_seconds())


def _bars(symbol: str, day: date) -> tuple[pd.DataFrame, str]:
    tk = yf.Ticker(yahoo_symbol(symbol))
    start, end = day - timedelta(days=6), day + timedelta(days=1)
    age = (datetime.now(ET).date() - day).days
    for interval, ok in (("5m", age <= 58), ("60m", age <= 720), ("1d", True)):
        if not ok:
            continue
        s = start if interval != "1d" else day - timedelta(days=200)
        e = end if interval != "1d" else day + timedelta(days=30)
        df = tk.history(start=s, end=e, interval=interval, prepost=interval != "1d", auto_adjust=True)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = df.index.tz_convert(ET) if df.index.tz is not None else df.index.tz_localize(ET)
            return df.dropna(subset=["Open", "High", "Low", "Close"]), interval
    return pd.DataFrame(), "none"


def _series(df: pd.DataFrame, values: pd.Series) -> list[dict]:
    return [{"time": _ts(t), "value": round(float(v), 4)} for t, v in values.items()
            if t in df.index and v == v and not math.isinf(v)]


def ticker_info(symbol: str) -> dict:
    hit = _info_cache.get(symbol)
    if hit and _time.monotonic() - hit[0] < 6 * 3600:
        return hit[1]
    try:
        i = yf.Ticker(yahoo_symbol(symbol)).info or {}
    except Exception:
        i = {}
    keys = ["longName", "shortName", "exchange", "sector", "industry", "country", "marketCap", "averageVolume",
            "averageVolume10days", "floatShares", "sharesOutstanding", "shortPercentOfFloat", "beta",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "trailingPE", "forwardPE", "dividendYield", "website",
            "fullTimeEmployees", "earningsTimestamp", "longBusinessSummary", "currency"]
    info = {k: i.get(k) for k in keys if i.get(k) not in (None, "", "N/A")}
    if "longBusinessSummary" in info:
        info["longBusinessSummary"] = str(info["longBusinessSummary"])[:700]
    _info_cache[symbol] = (_time.monotonic(), info)
    return info


def bot_markers(symbol: str, day: date) -> tuple[list[dict], list[dict]]:
    """(markers, trades) for the bot's paper trades in `symbol` on `day`."""
    markers, rows = [], []
    for r in read_trades():
        if r["symbol"] != symbol or not r["timestamp_iso"].startswith(day.isoformat()):
            continue
        t = datetime.fromisoformat(r["timestamp_iso"])
        buy = r["side"] == "BUY"
        markers.append({"time": t, "side": r["side"], "qty": r["size"], "price": float(r["fill_price"] or 0),
                        "text": f"{'BUY' if buy else 'SELL'} {r['size']} @ {float(r['fill_price'] or 0):.2f}"
                                + ("" if buy else f" ({r.get('status') or ''})"),
                        "stop": float(r["stop_price"]) if buy and r.get("stop_price") else None,
                        "strategy": r.get("strategy") or "trend_join_long"})
        rows.append(r)
    return markers, rows


def live_markers(symbol: str, day: date, account: str | None) -> list[dict]:
    from src import live_import
    out = []
    for f in live_import.load_fills():
        if f["symbol"] != symbol or not f["time"].startswith(day.isoformat()):
            continue
        if account and (f.get("account") or "") != account:
            continue
        out.append({"time": datetime.fromisoformat(f["time"]), "side": f["side"], "qty": f["qty"], "price": f["price"],
                    "text": f"{f['side']} {f['qty']:g} @ {f['price']:.2f}", "stop": None, "strategy": None})
    return out


def bot_reasons(symbol: str, day: date) -> list[dict]:
    """The bot's own log for this stock that day: why it bought, stop moves, exits."""
    out = []
    if not SAFETY_LOG_PATH.exists():
        return out
    with SAFETY_LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            if f'"{symbol}"' not in line or day.isoformat() not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("symbol") == symbol and str(e.get("ts", "")).startswith(day.isoformat()):
                if e.get("event") == "evaluate" and not e.get("passed"):
                    continue  # keep the story short: only the passing check, entries and management
                out.append({k: v for k, v in e.items() if k != "metrics"})
    return out[-40:]


def chart(symbol: str, day: date, source: str = "bot", account: str | None = None, or_minutes: int = 15) -> dict:
    df, interval = _bars(symbol, day)
    res = {"symbol": symbol, "date": day.isoformat(), "interval": interval, "candles": [], "volume": [],
           "lines": {}, "levels": {}, "markers": [], "reasons": [], "info": ticker_info(symbol)}
    if df.empty:
        res["error"] = "No price data from Yahoo for this date."
        return res

    closes = df["Close"]
    lines = {}
    if interval != "1d":
        for n in (9, 20, 50):
            lines[f"EMA {n}"] = closes.ewm(span=n, adjust=False).mean()
    else:
        for n in (20, 50, 200):
            lines[f"SMA {n}"] = closes.rolling(n).mean()

    if interval == "1d":
        view = df[(df.index.date >= day - timedelta(days=120)) & (df.index.date <= day + timedelta(days=20))]
    else:
        view = _day(df, day)
        if view.empty:
            res["error"] = "No bars for that day (weekend or holiday?)."
            return res
        rth = _day(_rth(df), day)
        if not rth.empty:
            tp = (rth["High"] + rth["Low"] + rth["Close"]) / 3
            lines["VWAP"] = (tp * rth["Volume"]).cumsum() / rth["Volume"].cumsum().replace(0, float("nan"))
            n = max(1, or_minutes // (5 if interval == "5m" else 60))
            first = rth.iloc[:n]
            res["levels"]["Opening range high"] = float(first["High"].max())
            res["levels"]["Opening range low"] = float(first["Low"].min())
        pm = view[view.index.time < RTH_OPEN]
        if not pm.empty:
            res["levels"]["Premarket high"] = float(pm["High"].max())
        prev = df[df.index.date < day]
        if not prev.empty:
            prev_rth = _rth(prev)
            last_day = prev_rth.index.date.max() if not prev_rth.empty else None
            if last_day:
                y = prev_rth[prev_rth.index.date == last_day]
                res["levels"]["Yesterday high"] = float(y["High"].max())
                res["levels"]["Yesterday close"] = float(y["Close"].iloc[-1])

    res["candles"] = [{"time": _ts(t), "open": round(float(r.Open), 4), "high": round(float(r.High), 4),
                       "low": round(float(r.Low), 4), "close": round(float(r.Close), 4)} for t, r in view.iterrows()]
    res["volume"] = [{"time": _ts(t), "value": float(r.Volume), "up": bool(r.Close >= r.Open)} for t, r in view.iterrows()]
    res["lines"] = {name: _series(view, s) for name, s in lines.items()}

    marks = live_markers(symbol, day, account) if source == "live" else bot_markers(symbol, day)[0]
    bar_times = list(view.index)
    for m in marks:
        # snap to the bar that contains the fill
        bt = max([t for t in bar_times if t <= m["time"]], default=bar_times[0])
        res["markers"].append({**m, "time": _ts(bt), "at": m["time"].strftime("%H:%M:%S")})
    stops = [m["stop"] for m in marks if m.get("stop")]
    if stops:
        res["levels"]["Initial stop"] = stops[0]
    if source != "live":
        res["reasons"] = bot_reasons(symbol, day)
    return res
