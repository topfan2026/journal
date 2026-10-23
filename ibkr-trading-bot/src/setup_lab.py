"""Setup Finder: replays recent days candle by candle through the bot's OWN entry code (strategies.evaluate)
and a simulation of its exits (stop, partial, breakeven, take-profit, trail under 5-minute swings,
15:51 close), then ranks every setup by what actually happened. No look-ahead: at each decision the
candle being formed only shows its opening price.

Results are a measurement of the recent past on your stocks, not a promise about the future."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta

import pandas as pd

from src import strategies as st
from src.common import PROJECT_DIR, to_py
from src.filters import _rth, swing_highs, swing_lows

RESULTS_PATH = PROJECT_DIR / "lab_results.json"
PROGRESS_PATH = PROJECT_DIR / "lab_progress.json"
FORCE_CLOSE = time(15, 51)
SLIP_PCT = 0.03  # % of price lost on each entry and on stop exits (spread + slippage)
DEFAULT_TICKERS = "SPY,QQQ,AAPL,NVDA,TSLA,AMD,META,MSFT,AMZN,GOOGL"


def _c(a, op, b, an=0, bn=0, x=1):
    return {"a": a, "an": an, "op": op, "b": b, "bn": bn, "x": x}


# Classic intraday setups, each with its idea, its trigger and its stop. All are tested the same way.
PLAYBOOK = [
    {"id": "orb15", "name": "Opening Range Breakout (15 min)", "kind": "orb", "side": "long",
     "why": "The first 15 minutes set the day's battle lines; a clean break above them on volume often runs.",
     "params": {"or_minutes": "15", "min_rvol": 0, "above_vwap": True}},
    {"id": "pm_break", "name": "Premarket High / Low Break (1 min)", "kind": "pm_break", "side": "both",
     "why": "Premarket highs/lows are levels everyone watches; holding beyond them for 2 candles shows real demand/supply.",
     "params": {}},
    {"id": "vwap_reclaim", "name": "VWAP Reclaim on Volume", "kind": "custom", "side": "long",
     "why": "VWAP is the institutions' benchmark; reclaiming it on heavy volume flips control to buyers.",
     "params": {"side": "long", "timeframe": "5m", "earliest_entry_et": "09:45", "latest_entry_et": "15:00",
                "conditions": [_c("close", "crosses_above", "vwap"), _c("volume", ">", "avg_volume", bn=20, x=1.5)]}},
    {"id": "vwap_reject", "name": "VWAP Rejection Short", "kind": "custom", "side": "short",
     "why": "Losing VWAP on heavy volume puts sellers in control; shorts the breakdown with a stop above the candle.",
     "params": {"side": "short", "timeframe": "5m", "earliest_entry_et": "09:45", "latest_entry_et": "15:00",
                "conditions": [_c("close", "crosses_below", "vwap"), _c("volume", ">", "avg_volume", bn=20, x=1.5)]}},
    {"id": "hod_break", "name": "High-of-Day Breakout", "kind": "custom", "side": "long",
     "why": "New highs above VWAP on 2× volume: momentum traders' bread and butter; stop under the last 3 candles.",
     "params": {"side": "long", "timeframe": "5m", "earliest_entry_et": "09:50", "latest_entry_et": "14:30",
                "stop_rule": "n_bars", "stop_n": 3,
                "conditions": [_c("close", "crosses_above", "day_high"), _c("close", ">", "vwap"),
                               _c("volume", ">", "avg_volume", bn=20, x=2)]}},
    {"id": "lod_break", "name": "Low-of-Day Breakdown Short", "kind": "custom", "side": "short",
     "why": "Mirror of the HOD breakout: new lows below VWAP on 2× volume; stop above the last 3 candles.",
     "params": {"side": "short", "timeframe": "5m", "earliest_entry_et": "09:50", "latest_entry_et": "14:30",
                "stop_rule": "n_bars", "stop_n": 3,
                "conditions": [_c("close", "crosses_below", "day_low"), _c("close", "<", "vwap"),
                               _c("volume", ">", "avg_volume", bn=20, x=2)]}},
    {"id": "ema9_trend", "name": "EMA 9 Pullback in an Uptrend", "kind": "custom", "side": "long",
     "why": "In a trend (EMA 9 > EMA 20, above VWAP) buys the candle that closes back above the EMA 9 after a dip.",
     "params": {"side": "long", "timeframe": "5m", "earliest_entry_et": "10:00", "latest_entry_et": "15:00",
                "stop_rule": "n_bars", "stop_n": 3,
                "conditions": [_c("close", "crosses_above", "ema", bn=9), _c("ema", ">", "ema", an=9, bn=20),
                               _c("close", ">", "vwap")]}},
    {"id": "red_green", "name": "Red-to-Green Move", "kind": "custom", "side": "long",
     "why": "Opens below yesterday's close, then reclaims it on volume: trapped shorts have to cover.",
     "params": {"side": "long", "timeframe": "5m", "earliest_entry_et": "09:35", "latest_entry_et": "11:30",
                "stop_rule": "day",
                "conditions": [_c("close", "crosses_above", "yday_close"), _c("today_open", "<", "yday_close"),
                               _c("volume", ">", "avg_volume", bn=20, x=1.5)]}},
    {"id": "yday_high", "name": "Yesterday's High Breakout", "kind": "custom", "side": "long",
     "why": "Clearing yesterday's high above VWAP on volume means every holder from yesterday is in profit.",
     "params": {"side": "long", "timeframe": "5m", "earliest_entry_et": "09:40", "latest_entry_et": "13:00",
                "conditions": [_c("close", "crosses_above", "yday_high"), _c("close", ">", "vwap"),
                               _c("volume", ">", "avg_volume", bn=20, x=1.5)]}},
    {"id": "ema_cross", "name": "EMA 9 / 21 Cross", "kind": "ema_cross", "side": "long",
     "why": "Fast trend-following trigger: the 9 EMA crossing above the 21 EMA on 5-minute candles.",
     "params": {"above_vwap": True}},
    {"id": "ht_vwap", "name": "HT_VWAP_Reclaim_Long", "kind": "ht_vwap_reclaim", "side": "long",
     "why": "HumbledTrader's VWAP setups: a reclaim on a volume push or a quiet pullback to VWAP.", "params": {}},
]


# ---------------------------------------------------------------- simulation

def _forming(frame: pd.DataFrame) -> pd.DataFrame:
    """The newest candle as seen 20 s after it opened: only its open is known (no look-ahead)."""
    f = frame.copy()
    if len(f):
        o = f["Open"].iloc[-1]
        f.iloc[-1, f.columns.get_indexer(["High", "Low", "Close"])] = o
        f.iloc[-1, f.columns.get_loc("Volume")] = 0
    return f


def _five_from_one(prior5: pd.DataFrame, today1: pd.DataFrame) -> pd.DataFrame:
    agg = today1.resample("5min", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Open"])
    return pd.concat([prior5, agg])


def _exit(cfg: dict, side: int, entry: float, stop: float, path: pd.DataFrame, day5: pd.DataFrame, tf: int,
          entry_t) -> tuple[float, str, str, float]:
    """Simulate the bot's exits on the candles after entry. Returns (R result, reason, exit time, last exit price).
    Within a candle the stop is assumed to be hit before any target (conservative)."""
    ex = cfg["exit"]
    R = abs(entry - stop)
    part_R, part_f = float(ex["partial_profit_trigger_R"]), float(ex["partial_profit_fraction"])
    be_R, tp_R, trail = float(ex["breakeven_trigger_R"]), float(ex.get("take_profit_R") or 0), bool(ex.get("trail"))
    left, got, be, partial = 1.0, 0.0, False, False
    slip = entry * SLIP_PCT / 100
    for t, b in path.iterrows():
        if (t + timedelta(minutes=tf)).time() > FORCE_CLOSE or t.time() >= FORCE_CLOSE:  # the candle holding 15:51
            return got + left * (b.Open - entry) * side / R, "end of day", t.strftime("%H:%M"), float(b.Open)
        adverse = b.Low if side > 0 else b.High
        if (adverse - stop) * side <= 0:
            fill = (min(stop, b.Open) if side > 0 else max(stop, b.Open)) - side * slip
            return got + left * (fill - entry) * side / R, "stop" if not be else "stop (after breakeven/trail)", t.strftime("%H:%M"), float(fill)
        best = ((b.High if side > 0 else b.Low) - entry) * side / R
        if tp_R and best >= tp_R:
            return got + left * tp_R, "target", t.strftime("%H:%M"), float(entry + side * tp_R * R)
        if not partial and part_R < 999 and best >= part_R:
            got += part_f * part_R
            left -= part_f
            partial = True
        if not be and be_R < 999 and best >= be_R:
            stop, be = entry, True
        if be and trail:
            end = t + timedelta(minutes=tf)
            done5 = day5[(day5.index + timedelta(minutes=5) <= end) & (day5.index >= entry_t)]
            pts = swing_lows(done5, 2, 2) if side > 0 else swing_highs(done5, 2, 2)
            if pts:
                cand = pts[-1][1] - 0.01 * side
                if (cand - stop) * side > 0 and (b.Close - cand) * side > 0:
                    stop = cand
    last = path.iloc[-1]
    return got + left * (last.Close - entry) * side / R, "end of data", path.index[-1].strftime("%H:%M"), float(last.Close)


def _gate(cfg: dict, hist: pd.DataFrame, d: date, dprior, tf: int):
    """Times worth a full check (None = check every candle). Pure speed-up: the full check still decides."""
    if cfg["type"] == "custom":
        from src.builder import signal_times
        return set(signal_times(cfg["params"], hist, d, dprior, tf))
    if cfg["type"] == "pm_break":
        day = hist[hist.index.date == d]
        pm = day[(day.index.time >= time(4, 0)) & (day.index.time < time(9, 30))]
        if pm.empty:
            return set()
        rth = _rth(day)
        beyond = (rth["Close"] > pm["High"].max()) | (rth["Close"] < pm["Low"].min())
        return {t + timedelta(minutes=tf) for t in rth.index[beyond.values]}
    return None


def _trim(frame: pd.DataFrame, d: date, keep_days: int = 3) -> pd.DataFrame:
    """The day itself (with premarket) plus the regular hours of the previous few trading days: enough for EMAs."""
    before = frame[frame.index.date < d]
    prev_days = sorted(set(before.index.date))[-keep_days:]
    return pd.concat([_rth(before[pd.Index(before.index.date).isin(prev_days)]), frame[frame.index.date == d]])


def backtest_symbol(cfg: dict, sym: str, daily: pd.DataFrame, intra5: pd.DataFrame, intra1: pd.DataFrame | None,
                    days: list[date], rules: dict, progress=None) -> list[dict]:
    one = cfg.get("timeframe") == "1m"
    tf = 1 if one else 5
    bars_all = intra1 if one else intra5
    if bars_all is None or bars_all.empty:
        return []
    e0, e1 = st.hhmm(cfg["earliest_entry_et"]), st.hhmm(cfg["latest_entry_et"])
    trades = []
    for d in days:
        if progress:
            progress()
        start = pd.Timestamp(datetime.combine(d - timedelta(days=7), time(0, 0))).tz_localize(bars_all.index.tz)
        end_d = pd.Timestamp(datetime.combine(d + timedelta(days=1), time(0, 0))).tz_localize(bars_all.index.tz)
        hist = _trim(bars_all[(bars_all.index >= start) & (bars_all.index < end_d)], d)
        day_rth = _rth(hist[hist.index.date == d])
        if day_rth.empty:
            continue
        hist5 = intra5[(intra5.index >= start) & (intra5.index < end_d)]
        day5 = _rth(hist5[hist5.index.date == d])
        prior5 = _rth(hist5[hist5.index.date < d]).iloc[-240:]
        dprior = daily[daily.index.map(lambda x: pd.Timestamp(x).date() < d)].iloc[-210:]
        gate = _gate(cfg, hist, d, dprior, tf)
        n_today, busy_until = 0, None
        for t in day_rth.index:
            if not (e0 <= t.time() <= e1) or n_today >= int(cfg["max_trades_per_day"]):
                continue
            if gate is not None and t not in gate:
                continue
            if busy_until is not None and t <= busy_until:
                continue
            seen = _forming(hist[hist.index <= t])
            price = float(seen["Open"].iloc[-1])
            now_t = (t + timedelta(seconds=20)).time()
            if one:
                intra = _five_from_one(prior5, seen[seen.index.date == d])
                res = st.evaluate(cfg, dprior, intra, price, d, rules, now_t, symbol=sym, bars_1m=seen)
            else:
                res = st.evaluate(cfg, dprior, seen, price, d, rules, now_t, symbol=sym)
            if not res["pass"]:
                continue
            m = res["metrics"]
            side = -1 if m.get("side") == "short" else 1
            stop = float(m["stop"])
            entry = price * (1 + side * SLIP_PCT / 100)
            if (entry - stop) * side <= 0:
                continue
            path = day_rth[day_rth.index >= t]
            r, why, out_t, out_px = _exit(cfg, side, entry, stop, path, day5, tf, t)
            trades.append({"symbol": sym, "date": d.isoformat(), "time": t.strftime("%H:%M"), "side": "short" if side < 0 else "long",
                           "entry": round(entry, 2), "stop": round(stop, 2), "R": round(r, 3), "exit": why, "exit_time": out_t,
                           "exit_price": round(out_px, 2)})
            n_today += 1
            busy_until = pd.Timestamp(datetime.combine(d, datetime.strptime(out_t, "%H:%M").time())).tz_localize(t.tz)
    return trades


# ---------------------------------------------------------------- scoring

def stats(trades: list[dict], days: list[date]) -> dict:
    rs = [t["R"] for t in sorted(trades, key=lambda t: (t["date"], t["time"]))]
    n = len(rs)
    out = {"trades": n, "win_rate": 0.0, "avg_R": 0.0, "total_R": 0.0, "profit_factor": None, "max_dd_R": 0.0,
           "avg_win_R": 0.0, "avg_loss_R": 0.0, "curve": [], "recent_avg_R": None, "early_avg_R": None, "score": -99.0}
    if not n:
        out["verdict"] = "No trades"
        return out
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append(round(cum, 2))
    split = days[len(days) * 2 // 3].isoformat() if len(days) >= 3 else None
    early = [t["R"] for t in trades if split and t["date"] < split]
    late = [t["R"] for t in trades if split and t["date"] >= split]
    avg = sum(rs) / n
    out.update(win_rate=len(wins) / n * 100, avg_R=avg, total_R=sum(rs), max_dd_R=dd, curve=curve,
               profit_factor=(sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
               avg_win_R=sum(wins) / len(wins) if wins else 0.0, avg_loss_R=sum(losses) / len(losses) if losses else 0.0,
               early_avg_R=sum(early) / len(early) if early else None, recent_avg_R=sum(late) / len(late) if late else None,
               score=avg * math.sqrt(n))
    pf = out["profit_factor"] if out["profit_factor"] is not None else (99 if wins else 0)
    holds = out["recent_avg_R"] is None or out["recent_avg_R"] > 0
    if n < 15:
        out["verdict"] = "Not enough trades"
    elif avg >= 0.2 and pf >= 1.3 and holds:
        out["verdict"] = "Strong"
    elif avg > 0.05 and pf >= 1.1:
        out["verdict"] = "Promising"
    else:
        out["verdict"] = "Weak"
    by_sym: dict[str, list[float]] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t["R"])
    out["by_symbol"] = sorted(([s, len(v), round(sum(v), 2)] for s, v in by_sym.items()), key=lambda x: -x[2])
    return out


def candidates(rules: dict, tickers: list[str], include_mine: bool = True) -> list[dict]:
    """Playbook setups plus the user's own strategies, as bot configs."""
    out = []
    for p in PLAYBOOK:
        params = {**st.defaults_for(p["kind"]), **p["params"], "universe": "custom", "tickers": ",".join(tickers)}
        s = {"id": "lab_" + p["id"], "type": p["kind"], "name": p["name"], "params": params}
        out.append({"id": p["id"], "name": p["name"], "kind": p["kind"], "side": p["side"], "why": p["why"],
                    "source": "playbook", "params": params, "cfg": st.config(s, rules)})
    if include_mine:
        for s in st.load():
            if s["type"] != "trend_join":
                s = {**s, "params": {**s["params"], "universe": "custom", "tickers": ",".join(tickers)}}
            cfg = st.config(s, rules)
            out.append({"id": "mine_" + s["id"], "strategy_id": s["id"], "name": s.get("name") or cfg["name"], "kind": s["type"],
                        "side": (s.get("params") or {}).get("side") or (s.get("params") or {}).get("direction") or "long",
                        "why": "Your strategy" + (" (switched on)" if s.get("enabled") else ""), "source": "mine",
                        "enabled": bool(s.get("enabled")), "cfg": cfg})
    return out


def _symbol_job(sym: str, data: tuple, cands: list, rules: dict) -> tuple[dict, list]:
    """Every setup on one stock (runs in a worker process)."""
    daily, i5, i1 = data
    out, errs = {}, []
    for cid, name, cfg, cdays in cands:
        try:
            out[cid] = backtest_symbol(cfg, sym, daily, i5, i1, cdays, rules)
        except Exception as exc:
            out[cid] = []
            errs.append(f"{name} / {sym}: {exc!r}"[:200])
    return out, errs


def run(tickers: list[str], n_days: int, rules: dict, loader, include_mine: bool = True, report=None,
        workers: int = 1) -> dict:
    """loader(symbol) -> (daily, intra5, intra1|None). report(done, total, note) for progress."""
    cands = candidates(rules, tickers, include_mine)
    data, errors = {}, []
    for i, sym in enumerate(tickers):
        if report:
            report(0, 1, f"Downloading {sym} ({i + 1}/{len(tickers)})")
        try:
            data[sym] = loader(sym)
        except Exception as exc:  # one bad ticker shouldn't stop the test
            errors.append(f"{sym}: {exc!r}"[:200])
    all_days = sorted({x for d in data.values() for x in _rth(d[1]).index.date})
    days = all_days[-n_days:]
    days1 = sorted({x for d in data.values() if d[2] is not None for x in _rth(d[2]).index.date})
    cdays_of = {c["id"]: [d for d in days if c["cfg"].get("timeframe") != "1m" or d in days1] for c in cands}
    jobs = [(sym, data[sym], [(c["id"], c["name"], c["cfg"], cdays_of[c["id"]]) for c in cands], rules) for sym in data]
    trades_of: dict[str, list] = {c["id"]: [] for c in cands}
    if report:
        report(0, max(1, len(jobs)), "Replaying the market candle by candle")

    def collect(out, n):
        trades, errs = out
        for cid, t in trades.items():
            trades_of[cid] += t
        errors.extend(errs)
        if report:
            report(n, len(jobs), "Replaying the market candle by candle")

    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futs = [pool.submit(_symbol_job, *j) for j in jobs]
            for n, f in enumerate(as_completed(futs), 1):
                collect(f.result(), n)
    else:
        for n, j in enumerate(jobs, 1):
            collect(_symbol_job(*j), n)

    results = []
    for c in cands:
        cdays, trades = cdays_of[c["id"]], trades_of[c["id"]]
        res = {k: v for k, v in c.items() if k != "cfg"}
        res.update(stats(trades, cdays), days=len(cdays), first_day=cdays[0].isoformat() if cdays else None,
                   last_day=cdays[-1].isoformat() if cdays else None, sample=sorted(trades, key=lambda t: (t["date"], t["time"]))[-60:])
        results.append(res)
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"finished": datetime.now().isoformat(timespec="seconds"), "tickers": tickers, "days": len(days),
            "first_day": days[0].isoformat() if days else None, "last_day": days[-1].isoformat() if days else None,
            "slippage_pct": SLIP_PCT, "results": results, "errors": errors[:20]}


def save_results(res: dict) -> None:
    tmp = RESULTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(to_py(res)), encoding="utf-8")
    tmp.replace(RESULTS_PATH)


def load_results() -> dict | None:
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def preset(setup_id: str) -> dict | None:
    return next((p for p in PLAYBOOK if p["id"] == setup_id), None)
