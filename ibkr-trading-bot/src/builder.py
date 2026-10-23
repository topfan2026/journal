"""Custom strategies built in the app from building blocks: "<A> <op> <B> [× factor]" conditions, all
checked on the newest COMPLETED candle (1- or 5-minute). Every value is shown in the bot's reasons so
you can see exactly why it did or didn't trade."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta

import pandas as pd

from src.filters import _day, _rth

# key: (label, label of its number or None, default number)
OPERANDS = {
    "close": ("Candle close", None, 0),
    "open": ("Candle open", None, 0),
    "high": ("Candle high", None, 0),
    "low": ("Candle low", None, 0),
    "prev_close": ("Previous candle close", None, 0),
    "prev_high": ("Previous candle high", None, 0),
    "prev_low": ("Previous candle low", None, 0),
    "ema": ("EMA", "length", 9),
    "sma": ("SMA", "length", 20),
    "vwap": ("VWAP", None, 0),
    "rsi": ("RSI", "length", 14),
    "volume": ("Candle volume", None, 0),
    "avg_volume": ("Average volume", "candles", 20),
    "day_high": ("High of day (before this candle)", None, 0),
    "day_low": ("Low of day (before this candle)", None, 0),
    "today_open": ("Today's open (9:30)", None, 0),
    "pm_high": ("Premarket high", None, 0),
    "pm_low": ("Premarket low", None, 0),
    "or_high": ("Opening range high", "minutes", 15),
    "or_low": ("Opening range low", "minutes", 15),
    "yday_high": ("Yesterday's high", None, 0),
    "yday_low": ("Yesterday's low", None, 0),
    "yday_close": ("Yesterday's close", None, 0),
    "number": ("Number", "value", 0),
}
OPS = {">": "is above", "<": "is below", "crosses_above": "crosses above", "crosses_below": "crosses below"}
MAX_CONDITIONS = 8

DEFAULT_CONDITIONS = [
    {"a": "close", "an": 0, "op": "crosses_above", "b": "vwap", "bn": 0, "x": 1},
    {"a": "volume", "an": 0, "op": ">", "b": "avg_volume", "bn": 20, "x": 1.5},
]


def operand_catalog() -> list[list]:
    return [[k, lab, nl, d] for k, (lab, nl, d) in OPERANDS.items()]


def clean_conditions(raw) -> list[dict]:
    """Validate what the app sent (a list or its JSON text)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
    out = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or c.get("a") not in OPERANDS or c.get("b") not in OPERANDS or c.get("op") not in OPS:
            continue
        def num(v, d):
            try:
                v = float(v)
                return v if math.isfinite(v) else d
            except (TypeError, ValueError):
                return d
        an, bn = num(c.get("an"), OPERANDS[c["a"]][2]), num(c.get("bn"), OPERANDS[c["b"]][2])
        if OPERANDS[c["a"]][1] and c["a"] != "number":
            an = max(1, min(500, round(an)))
        if OPERANDS[c["b"]][1] and c["b"] != "number":
            bn = max(1, min(500, round(bn)))
        out.append({"a": c["a"], "an": an, "op": c["op"], "b": c["b"], "bn": bn, "x": num(c.get("x"), 1) or 1})
    return out[:MAX_CONDITIONS]


def name_of(key: str, n) -> str:
    lab, nl, _ = OPERANDS[key]
    if key == "number":
        return f"{n:g}"
    return f"{lab} {n:g}" if nl else lab


def describe(c: dict) -> str:
    right = name_of(c["b"], c["bn"])
    if c["x"] != 1:
        right = f"{c['x']:g} × {right}"
    return f"{name_of(c['a'], c['an'])} {OPS[c['op']]} {right}"


# ---------------------------------------------------------------- series

def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, float("nan")))


def _series(key: str, n, rthc: pd.DataFrame, today: date, today_all: pd.DataFrame, prior_daily) -> pd.Series:
    idx = rthc.index
    is_today = pd.Series(idx.date == today, index=idx)
    T = rthc[is_today.values]

    def const(v) -> pd.Series:
        return pd.Series(float(v) if v is not None else float("nan"), index=idx).where(is_today)

    if key in ("close", "open", "high", "low", "volume"):
        return rthc[key.capitalize()].astype(float)
    if key.startswith("prev_"):
        return rthc[key[5:].capitalize()].astype(float).shift(1)
    if key == "ema":
        return rthc["Close"].ewm(span=int(n), adjust=False).mean()
    if key == "sma":
        return rthc["Close"].rolling(int(n)).mean()
    if key == "rsi":
        return _rsi(rthc["Close"].astype(float), int(n))
    if key == "avg_volume":
        return rthc["Volume"].astype(float).shift(1).rolling(int(n)).mean()
    if key == "number":
        return pd.Series(float(n), index=idx)
    if key == "vwap":
        tp = (T["High"] + T["Low"] + T["Close"]) / 3
        vw = (tp * T["Volume"]).cumsum() / T["Volume"].cumsum().replace(0, float("nan"))
        return vw.reindex(idx)
    if key in ("day_high", "day_low"):
        s = T["High"].cummax() if key == "day_high" else T["Low"].cummin()
        return s.shift(1).reindex(idx)
    if key == "today_open":
        return const(T["Open"].iloc[0] if len(T) else None)
    if key in ("pm_high", "pm_low"):
        pm = today_all[(today_all.index.time >= time(4, 0)) & (today_all.index.time < time(9, 30))]
        return const(None if pm.empty else (pm["High"].max() if key == "pm_high" else pm["Low"].min()))
    if key in ("or_high", "or_low"):
        end = (datetime.combine(today, time(9, 30)) + timedelta(minutes=int(n))).time()
        rng = T[T.index.time < end]
        v = None if rng.empty else (rng["High"].max() if key == "or_high" else rng["Low"].min())
        s = const(v)
        return s.where(pd.Series(idx.time >= end, index=idx))  # only once the range is finished
    if key.startswith("yday_"):
        col = key[5:].capitalize()
        if prior_daily is not None and not prior_daily.empty:
            return const(prior_daily[col].iloc[-1])
        prev = rthc[idx.date < today]
        if prev.empty:
            return const(None)
        last = prev[prev.index.date == prev.index.date.max()]
        return const({"High": last["High"].max(), "Low": last["Low"].min(), "Close": last["Close"].iloc[-1]}[col])
    raise KeyError(key)


# ---------------------------------------------------------------- evaluation

def evaluate(p: dict, bars: pd.DataFrame, today: date, price: float, prior_daily, checks, m,
             now_t: time | None, tf_minutes: int) -> float | None:
    """Appends checks, fills metrics; returns the stop (or None when there's nothing to trade)."""
    conds = clean_conditions(p.get("conditions"))
    if not conds:
        checks.append(("conditions", False, "no entry conditions set: add at least one in Edit"))
        return None
    side = "short" if p.get("side") == "short" else "long"
    m["side"] = side
    rth = _rth(bars)
    tf = pd.Timedelta(minutes=tf_minutes)
    if now_t is not None:
        now_dt = pd.Timestamp.combine(today, now_t)
        now_dt = now_dt.tz_localize(rth.index.tz) if rth.index.tz is not None else now_dt
        rthc = rth[rth.index + tf <= now_dt]  # completed candles by the clock
    else:
        now_dt, rthc = None, rth.iloc[:-1]
    T = rthc[rthc.index.date == today]
    if len(T) < 1:
        checks.append(("candles", False, "no completed candle today yet"))
        return None
    last_t = T.index[-1]
    m["signal_time"] = last_t.strftime("%H:%M")
    if now_dt is not None:
        age = (now_dt - (last_t + tf)).total_seconds() / 60
        if age > (0.75 if tf_minutes == 1 else 1.5):
            checks.append(("fresh", False, f"newest candle closed at {last_t + tf:%H:%M}, now {now_dt:%H:%M:%S}: data is behind"))
            return None
    today_all = _day(bars, today)

    cache: dict = {}

    def ser(k, n):
        if (k, n) not in cache:
            cache[(k, n)] = _series(k, n, rthc, today, today_all, prior_daily)
        return cache[(k, n)]

    flags = []
    for c in conds:
        a, b = ser(c["a"], c["an"]), ser(c["b"], c["bn"]) * c["x"]
        if c["op"] == ">":
            f = a > b
        elif c["op"] == "<":
            f = a < b
        elif c["op"] == "crosses_above":
            f = (a > b) & (a.shift(1) <= b.shift(1))
        else:
            f = (a < b) & (a.shift(1) >= b.shift(1))
        flags.append(f.fillna(False))
        va, vb = a.iloc[-1], b.iloc[-1]
        shown = lambda v: "n/a" if v != v else f"{v:,.2f}"
        checks.append(("if", bool(f.iloc[-1]), f"{describe(c)} ({shown(va)} vs {shown(vb)})"))
    if any(not bool(f.iloc[-1]) for f in flags):
        return None
    if p.get("fresh_only", True) and len(flags[0]) >= 2 and all(bool(f.iloc[-2]) for f in flags):
        checks.append(("new signal", False, "all conditions were already true on the candle before: not a new signal"))
        return None

    # ---- stop
    d = 1 if side == "long" else -1
    rule, n, buf = p.get("stop_rule", "bar"), float(p.get("stop_n", 3) or 3), float(p.get("stop_cents", 0.01) or 0)
    if rule == "n_bars":
        k = max(1, int(n))
        base = float(T["Low"].iloc[-k:].min()) if d > 0 else float(T["High"].iloc[-k:].max())
    elif rule == "day":
        base = float(T["Low"].min()) if d > 0 else float(T["High"].max())
    elif rule == "vwap":
        base = float(ser("vwap", 0).iloc[-1])
    elif rule == "ema":
        base = float(ser("ema", max(1, int(n))).iloc[-1])
    elif rule == "pct":
        base, buf = price * (1 - d * n / 100), 0.0
    else:  # the signal candle
        base = float(T["Low"].iloc[-1]) if d > 0 else float(T["High"].iloc[-1])
    if base != base:
        checks.append(("stop", False, "stop level not available yet"))
        return None
    stop = base - d * buf
    min_dist = price * float(p.get("min_stop_pct", 0) or 0) / 100
    if min_dist and (price - stop) * d < min_dist:
        m["stop_widened_from"] = round(stop, 2)
        stop = price - d * min_dist
    return round(stop, 2)


def signal_times(p: dict, bars: pd.DataFrame, today: date, prior_daily, tf_minutes: int) -> list:
    """Backtest speed-up: start times of the candles right after every candle where all conditions held
    (every building block only looks backwards, so this matches a candle-by-candle check)."""
    conds = clean_conditions(p.get("conditions"))
    if not conds:
        return []
    rthc = _rth(bars)
    today_all = _day(bars, today)
    flags = None
    for c in conds:
        a = _series(c["a"], c["an"], rthc, today, today_all, prior_daily)
        b = _series(c["b"], c["bn"], rthc, today, today_all, prior_daily) * c["x"]
        f = {">": a > b, "<": a < b, "crosses_above": (a > b) & (a.shift(1) <= b.shift(1)),
             "crosses_below": (a < b) & (a.shift(1) >= b.shift(1))}[c["op"]].fillna(False)
        flags = f if flags is None else flags & f
    if p.get("fresh_only", True):
        flags = flags & ~flags.shift(1, fill_value=False)
    hit = flags[(flags.index.date == today) & flags.values]
    return [t + pd.Timedelta(minutes=tf_minutes) for t in hit.index]
