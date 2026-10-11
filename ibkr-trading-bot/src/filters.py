"""Pure strategy math: the six Trend Join Long filters, swing lows and position sizing.

No network or broker calls in here, so everything can be unit-tested with synthetic bars.

Inputs:
- daily: DataFrame indexed by date (oldest first) with Open/High/Low/Close/Volume, at least
  ~201 rows so the 200-day SMA exists.
- intraday: 5-minute DataFrame with a tz-aware ET DatetimeIndex, INCLUDING pre/post-market bars
  (yfinance prepost=True), covering today plus the RVOL lookback days.
"""
from __future__ import annotations

import math
from datetime import date, time

import pandas as pd

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
PREMARKET_START = time(4, 0)


def _rth(bars: pd.DataFrame) -> pd.DataFrame:
    t = bars.index.time
    return bars[(t >= RTH_OPEN) & (t < RTH_CLOSE)]


def _day(bars: pd.DataFrame, d: date) -> pd.DataFrame:
    return bars[bars.index.date == d]


def compute_rvol(intraday: pd.DataFrame, today: date, lookback_days: int) -> float:
    """Cumulative RTH volume so far today vs. the average over the previous N days at the same time."""
    rth = _rth(intraday)
    today_bars = _day(rth, today)
    if today_bars.empty:
        return float("nan")
    cutoff = today_bars.index[-1].time()
    today_cum = float(today_bars["Volume"].sum())
    prior_days = sorted({d for d in rth.index.date if d < today})[-lookback_days:]
    sums = []
    for d in prior_days:
        day_bars = _day(rth, d)
        sums.append(float(day_bars[day_bars.index.time <= cutoff]["Volume"].sum()))
    sums = [s for s in sums if s > 0]
    if not sums:
        return float("nan")
    return today_cum / (sum(sums) / len(sums))


def evaluate_filters(daily: pd.DataFrame, intraday: pd.DataFrame, price: float, today: date, rules: dict) -> dict:
    """Run D1-D3 and I1-I3. Returns {"pass", "reasons", "metrics"}; checks every filter (no early exit)
    so the safety log shows exactly which ones failed."""
    df = rules["daily_filters"]
    intra = rules["intraday_filters"]
    reasons: list[str] = []
    m: dict = {"price": price}

    prior = daily[daily.index.map(lambda x: pd.Timestamp(x).date() < today)]
    today_rth = _day(_rth(intraday), today)
    if len(prior) < 200 or today_rth.empty or not price or math.isnan(price):
        return {"pass": False, "reasons": ["insufficient data (need 200 prior daily bars + today's 5m bars)"], "metrics": m}

    prior_high = float(prior["High"].iloc[-1])
    prior_close = float(prior["Close"].iloc[-1])
    sma200 = float(prior["Close"].iloc[-200:].mean())
    today_open = float(today_rth["Open"].iloc[0])
    gap_pct = (today_open - prior_close) / prior_close * 100
    m.update(prior_high=prior_high, prior_close=prior_close, sma200=sma200, today_open=today_open, gap_pct=gap_pct)

    checks: list[tuple[str, bool, str]] = []
    if df.get("D1_above_prior_day_high"):
        checks.append(("D1", price > prior_high, f"price {price:.2f} vs prior high {prior_high:.2f}"))
    if df.get("D2_prior_close_above_sma200"):
        checks.append(("D2", prior_close > sma200, f"prior close {prior_close:.2f} vs SMA200 {sma200:.2f}"))
    min_gap = df.get("D3_min_gap_pct_from_prior_close")
    if min_gap is not None:
        checks.append(("D3", gap_pct >= float(min_gap), f"gap {gap_pct:+.2f}% vs min {float(min_gap):.2f}%"))

    today_all = _day(intraday, today)
    pm = today_all[(today_all.index.time >= PREMARKET_START) & (today_all.index.time < RTH_OPEN)]
    if intra.get("I1_above_premarket_high"):
        if pm.empty:
            checks.append(("I1", False, "no premarket bars"))
        else:
            pm_high = float(pm["High"].max())
            m["premarket_high"] = pm_high
            checks.append(("I1", price > pm_high, f"price {price:.2f} vs PM high {pm_high:.2f}"))
    if intra.get("I2_above_today_hod"):
        # The newest 5m bar is still forming and already contains the current price, so compare
        # against the high of the completed bars: "price is making a new high of day".
        completed = today_rth.iloc[:-1]
        if completed.empty:
            checks.append(("I2", False, "no completed RTH bars yet"))
        else:
            hod = float(completed["High"].max())
            m["hod_so_far"] = hod
            checks.append(("I2", price > hod, f"price {price:.2f} vs HOD {hod:.2f}"))
    rvol_min = intra.get("I3_rvol_min")
    if rvol_min is not None:
        rvol = compute_rvol(intraday, today, int(intra.get("I3_rvol_lookback_days", 14)))
        m["rvol"] = rvol
        ok = not math.isnan(rvol) and rvol >= float(rvol_min)
        checks.append(("I3", ok, f"RVOL {rvol:.2f} vs min {float(rvol_min):.2f}"))

    m["low_of_day"] = float(today_rth["Low"].min())
    for name, ok, detail in checks:
        reasons.append(f"{name} {'ok' if ok else 'FAIL'}: {detail}")
    passed = bool(all(ok for _, ok, _ in checks))
    return {"pass": passed, "reasons": reasons, "metrics": m}


def initial_stop(low_of_day: float, rule: str = "lod_minus_1pct") -> float:
    if rule != "lod_minus_1pct":
        raise ValueError(f"unsupported initial_stop_rule: {rule}")
    return low_of_day * 0.99


def position_size(price: float, stop: float, portfolio: float, risk_pct: float,
                  max_position_pct: float, max_trade_usd: float) -> int:
    """Shares = risk budget / R, capped by % of portfolio and by MAX_TRADE_SIZE_USD."""
    r = price - stop
    if r <= 0 or price <= 0:
        return 0
    by_risk = math.floor(portfolio * risk_pct / 100 / r)
    by_cap = math.floor(min(portfolio * max_position_pct / 100, max_trade_usd) / price)
    return max(0, min(by_risk, by_cap))


def swing_lows(bars: pd.DataFrame, left: int = 2, right: int = 2) -> list[tuple[pd.Timestamp, float]]:
    """Bars whose low is strictly lower than the `left` bars before and the `right` bars after.
    Pass only COMPLETED bars; the last `right` bars can never qualify yet."""
    lows = bars["Low"].tolist()
    out = []
    for i in range(left, len(lows) - right):
        neighbours = lows[i - left:i] + lows[i + 1:i + 1 + right]
        if all(lows[i] < n for n in neighbours):
            out.append((bars.index[i], float(lows[i])))
    return out


def r_multiple(price: float, entry: float, stop: float) -> float:
    risk = entry - stop
    return (price - entry) / risk if risk > 0 else 0.0
