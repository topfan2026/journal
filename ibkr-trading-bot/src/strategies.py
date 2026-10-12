"""Strategy library: templates, the user's strategy list (strategies.json) and the entry logic.

Each strategy is long-only and paper traded by cycle.py. Trend Join Long keeps its settings in
rules.json (unchanged); every other strategy stores its own settings in strategies.json.
All strategies share the global limits in rules.json (max open positions, position size cap,
force-close time) and MAX_TRADES_PER_DAY in .env.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, time

import pandas as pd

from src.common import PROJECT_DIR, load_rules, to_py
from src.filters import _day, _rth, compute_rvol, evaluate_filters, initial_stop

STORE = PROJECT_DIR / "strategies.json"
TREND_JOIN_ID = "trend_join_long"

# ---------------------------------------------------------------- templates (drive the app's forms)

def _f(k, label, t, default, help="", group="Setup", **kw):
    return {"k": k, "label": label, "t": t, "def": default, "help": help, "group": group, **kw}


COMMON_FIELDS = [
    _f("universe", "Stocks to watch", "select", "gappers", "Today's gappers from the scanner, or your own list",
       opts=[["gappers", "Scanner gappers (watchlist)"], ["custom", "My ticker list"]]),
    _f("tickers", "My ticker list", "text", "SPY,QQQ,AAPL,NVDA,TSLA,AMD,META,MSFT,AMZN",
       "Comma-separated; used when 'My ticker list' is chosen"),
    _f("min_price", "Min price $", "num", 5.0, group="Filters", min=1, step=0.5),
    _f("min_gap_pct", "Min gap % (0 = off)", "num", 0.0, "Today's open vs yesterday's close", group="Filters", step=0.5),
    _f("min_rvol", "Min relative volume (0 = off)", "num", 0.0, "Volume so far vs normal at this time", group="Filters", step=0.1),
    _f("above_vwap", "Price above VWAP", "bool", True, group="Filters"),
    _f("above_sma200", "Daily uptrend (close > 200-day avg)", "bool", False, group="Filters"),
    _f("earliest_entry_et", "First entry (ET)", "time", "09:45", group="Timing"),
    _f("latest_entry_et", "Last entry (ET)", "time", "15:00", group="Timing"),
    _f("stop_buffer_pct", "Stop buffer %", "num", 0.1, "Extra room below the stop level", group="Exits", step=0.05, min=0),
    _f("partial_R", "Partial profit at R (0 = off)", "num", 1.0, group="Exits", step=0.25, min=0),
    _f("partial_fraction", "Partial size", "num", 0.5, "Share of the position sold at the partial", group="Exits",
       step=0.05, min=0.05, max=0.95),
    _f("breakeven_R", "Stop to breakeven at R (0 = off)", "num", 1.0, group="Exits", step=0.25, min=0),
    _f("take_profit_R", "Take full profit at R (0 = off)", "num", 0.0, group="Exits", step=0.5, min=0),
    _f("trail_swing", "Trail stop under 5-min swing lows", "bool", True, "After breakeven", group="Exits"),
    _f("risk_pct", "Risk per trade %", "num", 0.5, "Of the account, if the stop is hit", group="Risk", step=0.1, min=0.1, max=2),
    _f("max_trades_per_day", "Max trades per day", "num", 2, group="Risk", step=1, min=1, max=10),
]

TEMPLATES = {
    "trend_join": {
        "name": "Trend Join Long",
        "summary": "Gap-up stock above yesterday's high, the 200-day average and the premarket high, making a new "
                   "high of day on 2× volume. Stop under today's low.",
        "fields": [  # stored in rules.json
            _f("D3_min_gap_pct_from_prior_close", "Min gap %", "num", 3.0, path=["daily_filters", "D3_min_gap_pct_from_prior_close"], group="Filters", step=0.5),
            _f("D1_above_prior_day_high", "Above yesterday's high", "bool", True, path=["daily_filters", "D1_above_prior_day_high"], group="Filters"),
            _f("D2_prior_close_above_sma200", "Daily uptrend (200-day avg)", "bool", True, path=["daily_filters", "D2_prior_close_above_sma200"], group="Filters"),
            _f("I1_above_premarket_high", "Above premarket high", "bool", True, path=["intraday_filters", "I1_above_premarket_high"], group="Filters"),
            _f("I2_above_today_hod", "New high of day", "bool", True, path=["intraday_filters", "I2_above_today_hod"], group="Filters"),
            _f("I3_rvol_min", "Min relative volume", "num", 2.0, path=["intraday_filters", "I3_rvol_min"], group="Filters", step=0.1),
            _f("earliest_entry_et", "First entry (ET)", "time", "10:05", path=["time_filter", "earliest_entry_et"], group="Timing"),
            _f("latest_entry_et", "Last entry (ET)", "time", "15:30", path=["time_filter", "latest_entry_et"], group="Timing"),
            _f("partial_profit_trigger_R", "Partial profit at R", "num", 0.75, path=["exit", "partial_profit_trigger_R"], group="Exits", step=0.25),
            _f("partial_profit_fraction", "Partial size", "num", 0.3333, path=["exit", "partial_profit_fraction"], group="Exits", step=0.05),
            _f("breakeven_trigger_R", "Stop to breakeven at R", "num", 1.0, path=["exit", "breakeven_trigger_R"], group="Exits", step=0.25),
            _f("max_risk_per_trade_pct", "Risk per trade %", "num", 1.0, path=["risk", "max_risk_per_trade_pct"], group="Risk", step=0.1),
        ],
    },
    "orb": {
        "name": "Opening Range Breakout",
        "summary": "Marks the high and low of the first minutes after the open, then buys a fresh break above the "
                   "range high. Stop at the range low (or middle).",
        "fields": [
            _f("or_minutes", "Opening range (minutes)", "select", "15", opts=[["5", "5 min"], ["15", "15 min"], ["30", "30 min"]]),
            _f("max_or_range_pct", "Skip if range wider than %", "num", 3.0, "Very wide ranges mean a far-away stop", step=0.5),
            _f("fresh_bars", "Breakout must be within the last N bars", "num", 2, "Avoids buying long after the break", step=1, min=1, max=6),
            _f("stop_rule", "Stop at", "select", "or_low", group="Exits",
               opts=[["or_low", "Range low"], ["or_mid", "Middle of the range"], ["signal_low", "Low of the last 3 bars"]]),
        ],
        "overrides": {"earliest_entry_et": "09:45", "latest_entry_et": "11:30", "min_rvol": 1.5},
    },
    "ema_cross": {
        "name": "EMA Cross",
        "summary": "Buys when the fast EMA crosses above the slow EMA on the 5-minute chart (a new short-term uptrend).",
        "fields": [
            _f("fast", "Fast EMA", "num", 9, step=1, min=2, max=100),
            _f("slow", "Slow EMA", "num", 21, step=1, min=3, max=200),
            _f("fresh_bars", "Cross must be within the last N bars", "num", 2, step=1, min=1, max=6),
            _f("stop_rule", "Stop at", "select", "signal_low", group="Exits",
               opts=[["signal_low", "Low of the last 3 bars"], ["slow_ema", "Slow EMA"], ["lod", "Today's low"]]),
        ],
        "overrides": {"earliest_entry_et": "10:00"},
    },
    "price_cross_ema": {
        "name": "Price crosses EMA",
        "summary": "Buys when a 5-minute bar closes back above the EMA after being below it.",
        "fields": [
            _f("ema", "EMA length", "num", 20, step=1, min=2, max=200),
            _f("fresh_bars", "Cross must be within the last N bars", "num", 2, step=1, min=1, max=6),
            _f("stop_rule", "Stop at", "select", "signal_low", group="Exits",
               opts=[["signal_low", "Low of the last 3 bars"], ["ema", "The EMA"], ["lod", "Today's low"]]),
        ],
        "overrides": {"earliest_entry_et": "10:00"},
    },
    "ema_bounce": {
        "name": "EMA Bounce (pullback)",
        "summary": "In an uptrend (fast EMA above slow EMA), waits for a pullback that touches the EMA, then buys "
                   "when price moves back above the last bar's high.",
        "fields": [
            _f("ema", "Pullback EMA", "num", 20, step=1, min=2, max=200),
            _f("trend_ema", "Trend EMA (must be below)", "num", 50, step=1, min=3, max=300),
            _f("touch_pct", "Counts as a touch within %", "num", 0.2, step=0.05, min=0),
            _f("lookback", "Touch within the last N bars", "num", 3, step=1, min=1, max=10),
            _f("stop_rule", "Stop at", "select", "signal_low", group="Exits",
               opts=[["signal_low", "Pullback low"], ["ema", "The EMA"], ["lod", "Today's low"]]),
        ],
        "overrides": {"earliest_entry_et": "10:00"},
    },
}


def defaults_for(kind: str) -> dict:
    t = TEMPLATES[kind]
    if kind == "trend_join":
        return {}
    params = {f["k"]: f["def"] for f in COMMON_FIELDS + t["fields"]}
    params.update(t.get("overrides", {}))
    return params


def fields_for(kind: str) -> list[dict]:
    return TEMPLATES[kind]["fields"] if kind == "trend_join" else TEMPLATES[kind]["fields"] + COMMON_FIELDS


# ---------------------------------------------------------------- the user's list

def load() -> list[dict]:
    """strategies.json; created with Trend Join Long (active) the first time."""
    if STORE.exists():
        try:
            items = json.loads(STORE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    else:
        items = []
    if not any(s.get("id") == TREND_JOIN_ID for s in items):
        items.insert(0, {"id": TREND_JOIN_ID, "type": "trend_join", "name": "Trend Join Long", "enabled": True})
    for s in items:  # fill in settings added in later versions
        if s["type"] != "trend_join":
            s["params"] = {**defaults_for(s["type"]), **s.get("params", {})}
    return items


def save(items: list[dict]) -> None:
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(to_py(items), indent=2), encoding="utf-8")
    tmp.replace(STORE)


def new_id(kind: str, items: list[dict]) -> str:
    n = 1
    while any(s["id"] == f"{kind}_{n}" for s in items):
        n += 1
    return f"{kind}_{n}"


def coerce(kind: str, raw: dict) -> dict:
    """Validate form values against the template's field types."""
    out = {}
    for f in fields_for(kind):
        if f["k"] not in raw:
            continue
        v = raw[f["k"]]
        if f["t"] == "num":
            v = float(v)
            if "min" in f:
                v = max(f["min"], v)
            if "max" in f:
                v = min(f["max"], v)
            if float(f["def"]).is_integer() and f.get("step", 1) == 1:
                v = int(round(v))
        elif f["t"] == "bool":
            v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
        elif f["t"] == "time":
            if not re.fullmatch(r"\d{1,2}:\d{2}", str(v)):
                continue
            h, m = map(int, str(v).split(":"))
            v = f"{h:02d}:{m:02d}"
        elif f["t"] == "select":
            if str(v) not in [o[0] for o in f["opts"]]:
                continue
            v = str(v)
        else:
            v = str(v)[:2000]
        out[f["k"]] = v
    return out


def trend_join_values(rules: dict) -> dict:
    out = {}
    for f in TEMPLATES["trend_join"]["fields"]:
        node = rules
        for key in f["path"]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        out[f["k"]] = node if node != {} else f["def"]
    return out


def write_trend_join(values: dict) -> None:
    from src.common import RULES_PATH
    rules = load_rules()
    for f in TEMPLATES["trend_join"]["fields"]:
        if f["k"] in values:
            node = rules
            for key in f["path"][:-1]:
                node = node.setdefault(key, {})
            node[f["path"][-1]] = values[f["k"]]
    tmp = RULES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    tmp.replace(RULES_PATH)


def config(s: dict, rules: dict) -> dict:
    """One strategy's effective settings, in the same shape for every type."""
    if s["type"] == "trend_join":
        tf, ex = rules["time_filter"], rules["exit"]
        return {"id": s["id"], "name": s.get("name", "Trend Join Long"), "type": "trend_join",
                "universe": "gappers", "tickers": [],
                "earliest_entry_et": tf["earliest_entry_et"], "latest_entry_et": tf["latest_entry_et"],
                "min_price": float(rules["universe_filters"]["min_price_usd"]),
                "risk_pct": float(rules["risk"]["max_risk_per_trade_pct"]), "max_trades_per_day": 99,
                "exit": {"partial_profit_trigger_R": ex["partial_profit_trigger_R"],
                         "partial_profit_fraction": ex["partial_profit_fraction"],
                         "breakeven_trigger_R": ex["breakeven_trigger_R"], "take_profit_R": 0, "trail": True}}
    p = s["params"]
    return {"id": s["id"], "name": s.get("name") or TEMPLATES[s["type"]]["name"], "type": s["type"], "params": p,
            "universe": p["universe"],
            "tickers": [t.strip().upper() for t in str(p.get("tickers", "")).replace(";", ",").split(",") if t.strip()],
            "earliest_entry_et": p["earliest_entry_et"], "latest_entry_et": p["latest_entry_et"],
            "min_price": float(p["min_price"]), "risk_pct": float(p["risk_pct"]),
            "max_trades_per_day": int(p["max_trades_per_day"]),
            "exit": {"partial_profit_trigger_R": float(p["partial_R"]) or 999,
                     "partial_profit_fraction": float(p["partial_fraction"]),
                     "breakeven_trigger_R": float(p["breakeven_R"]) or 999,
                     "take_profit_R": float(p["take_profit_R"]), "trail": bool(p["trail_swing"])}}


def hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


# ---------------------------------------------------------------- indicators

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def vwap(today_rth: pd.DataFrame) -> float:
    tp = (today_rth["High"] + today_rth["Low"] + today_rth["Close"]) / 3
    vol = today_rth["Volume"].clip(lower=0)
    return float((tp * vol).sum() / vol.sum()) if vol.sum() > 0 else float("nan")


def _crossed_within(above: pd.Series, bars: int) -> bool:
    """True if `above` switched False->True within the last `bars` values and is True now."""
    if len(above) < 2 or not bool(above.iloc[-1]):
        return False
    recent = above.iloc[-(bars + 1):].tolist()
    return any((not a) and b for a, b in zip(recent, recent[1:]))


# ---------------------------------------------------------------- evaluation

def evaluate(cfg: dict, daily: pd.DataFrame, intraday: pd.DataFrame, price: float, today: date,
             rules: dict, now_t: time) -> dict:
    """{'pass', 'reasons', 'metrics' (incl. 'stop')}: every check is listed so the app shows why."""
    if cfg["type"] == "trend_join":
        res = evaluate_filters(daily, intraday, price, today, rules)
        if res["pass"]:
            res["metrics"]["stop"] = initial_stop(res["metrics"]["low_of_day"], rules["exit"]["initial_stop_rule"])
        return res

    p = cfg["params"]
    checks: list[tuple[str, bool, str]] = []
    m: dict = {"price": price}
    rth = _rth(intraday)
    today_rth = _day(rth, today)
    prior = daily[daily.index.map(lambda x: pd.Timestamp(x).date() < today)] if daily is not None and not daily.empty else daily
    if today_rth.empty or not price or math.isnan(price):
        return {"pass": False, "reasons": ["no data for today yet"], "metrics": m}
    completed = today_rth.iloc[:-1]  # newest 5-minute bar is still forming
    m["low_of_day"] = float(today_rth["Low"].min())

    # ---- common filters
    checks.append(("price", price >= float(p["min_price"]), f"price {price:.2f} vs min {float(p['min_price']):.2f}"))
    if float(p["min_gap_pct"]) > 0:
        if prior is None or prior.empty:
            checks.append(("gap", False, "no daily data"))
        else:
            gap = (float(today_rth["Open"].iloc[0]) / float(prior["Close"].iloc[-1]) - 1) * 100
            m["gap_pct"] = gap
            checks.append(("gap", gap >= float(p["min_gap_pct"]), f"gap {gap:+.2f}% vs min {float(p['min_gap_pct']):.1f}%"))
    if float(p["min_rvol"]) > 0:
        rv = compute_rvol(intraday, today, 14)
        m["rvol"] = rv
        checks.append(("volume", not math.isnan(rv) and rv >= float(p["min_rvol"]), f"RVOL {rv:.2f} vs min {float(p['min_rvol']):.1f}"))
    if p["above_vwap"]:
        vw = vwap(today_rth)
        m["vwap"] = vw
        checks.append(("vwap", price > vw, f"price {price:.2f} vs VWAP {vw:.2f}"))
    if p["above_sma200"]:
        ok = prior is not None and len(prior) >= 200 and float(prior["Close"].iloc[-1]) > float(prior["Close"].iloc[-200:].mean())
        checks.append(("trend", ok, "prior close vs 200-day average"))

    # ---- the strategy's own trigger
    closes = rth["Close"].iloc[:-1]  # completed bars across recent days, for EMAs
    level = None
    kind = cfg["type"]
    if kind == "orb":
        n = int(p["or_minutes"]) // 5
        if len(today_rth) <= n:
            checks.append(("range", False, f"opening range ({p['or_minutes']} min) not finished"))
        else:
            rng = today_rth.iloc[:n]
            hi, lo = float(rng["High"].max()), float(rng["Low"].min())
            m.update(or_high=hi, or_low=lo)
            width = (hi - lo) / hi * 100
            checks.append(("range", width <= float(p["max_or_range_pct"]), f"range {width:.2f}% vs max {float(p['max_or_range_pct']):.1f}%"))
            after = completed.iloc[n:]
            fresh = int(p["fresh_bars"])
            above = after["Close"] > hi
            broke = len(after) > 0 and bool(above.any()) and (len(after) - int(above.values.argmax())) <= fresh
            checks.append(("breakout", broke and price > hi, f"price {price:.2f} vs range high {hi:.2f} (fresh break)"))
            level = {"or_low": lo, "or_mid": (hi + lo) / 2}.get(p["stop_rule"])
    elif kind == "ema_cross":
        fast, slow = ema(closes, p["fast"]), ema(closes, p["slow"])
        m.update(fast_ema=float(fast.iloc[-1]), slow_ema=float(slow.iloc[-1]))
        checks.append(("cross", _crossed_within(fast > slow, int(p["fresh_bars"])),
                       f"EMA{int(p['fast'])} {fast.iloc[-1]:.2f} crossed above EMA{int(p['slow'])} {slow.iloc[-1]:.2f}"))
        level = {"slow_ema": float(slow.iloc[-1])}.get(p["stop_rule"])
    elif kind == "price_cross_ema":
        e = ema(closes, p["ema"])
        m["ema"] = float(e.iloc[-1])
        checks.append(("cross", _crossed_within(closes > e, int(p["fresh_bars"])) and price > float(e.iloc[-1]),
                       f"close crossed above EMA{int(p['ema'])} {e.iloc[-1]:.2f}"))
        level = {"ema": float(e.iloc[-1])}.get(p["stop_rule"])
    elif kind == "ema_bounce":
        e, t = ema(closes, p["ema"]), ema(closes, p["trend_ema"])
        m.update(ema=float(e.iloc[-1]), trend_ema=float(t.iloc[-1]))
        checks.append(("uptrend", float(e.iloc[-1]) > float(t.iloc[-1]), f"EMA{int(p['ema'])} above EMA{int(p['trend_ema'])}"))
        lb = int(p["lookback"])
        recent = completed.iloc[-lb:]
        e_recent = e.iloc[-lb:].values if len(e) >= lb else e.values
        touched = len(recent) > 0 and any(low <= ev * (1 + float(p["touch_pct"]) / 100)
                                          for low, ev in zip(recent["Low"].values, e_recent[-len(recent):]))
        last_high = float(completed["High"].iloc[-1]) if len(completed) else float("inf")
        checks.append(("pullback", touched, f"touched EMA{int(p['ema'])} in the last {lb} bars"))
        checks.append(("trigger", price > last_high and float(completed["Close"].iloc[-1]) > float(e.iloc[-1]) if len(completed) else False,
                       f"price {price:.2f} above last bar high {last_high:.2f}"))
        level = {"ema": float(e.iloc[-1])}.get(p["stop_rule"])

    if p.get("stop_rule") == "lod":
        level = m["low_of_day"]
    if level is None:  # signal_low
        level = float(completed["Low"].iloc[-3:].min()) if len(completed) else m["low_of_day"]
    stop = round(level * (1 - float(p["stop_buffer_pct"]) / 100), 2)
    m["stop"] = stop
    checks.append(("stop", stop < price, f"stop {stop:.2f} below price {price:.2f}"))

    reasons = [f"{name} {'ok' if ok else 'FAIL'}: {detail}" for name, ok, detail in checks]
    return {"pass": bool(all(ok for _, ok, _ in checks)), "reasons": reasons, "metrics": m}
