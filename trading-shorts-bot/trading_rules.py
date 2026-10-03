"""Strategy rules for the AI paper trader - plain functions on 1-minute bars, no IBKR needed.

Long-only intraday setups on scanner movers:
  ORB           opening-range breakout: a 1-min bar CLOSES above the high of the first
                TRADER_ORB_MIN minutes, on above-average volume. Stop = opening-range low
                (or mid-range if that is tighter), target = TRADER_TARGET_R x risk.
  VWAP reclaim  price spent at least TRADER_VWAP_BELOW bars below VWAP, then a bar closes back
                above VWAP on above-average volume. Stop = lowest low of the last few bars.

Risk: position size = TRADER_RISK_USD / (entry - stop), capped at TRADER_MAX_POSITION_USD.
Day limits: at most TRADER_MAX_TRADES trades, stop for the day after TRADER_MAX_LOSSES losses.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Bar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    symbol: str
    strategy: str
    entry: float
    stop: float
    target: float
    reason: str

    @property
    def risk(self) -> float:
        return self.entry - self.stop


def vwap_series(bars: list[Bar]) -> list[float]:
    """Running VWAP (typical price x volume) from the first bar of the session."""
    out, pv, vol = [], 0.0, 0.0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        pv += typical * b.volume
        vol += b.volume
        out.append(pv / vol if vol else b.close)
    return out


def avg_volume(bars: list[Bar], n: int = 10) -> float:
    recent = [b.volume for b in bars[-n:]]
    return sum(recent) / len(recent) if recent else 0.0


def opening_range(bars: list[Bar], minutes: int) -> tuple[float, float] | None:
    if len(bars) < minutes:
        return None
    first = bars[:minutes]
    return max(b.high for b in first), min(b.low for b in first)


def tick_round(price: float) -> float:
    return round(price, 2 if price >= 1 else 4)


def orb_signal(symbol: str, bars: list[Bar], orb_min: int = 5, vol_mult: float = 1.2,
               target_r: float = 2.0) -> Signal | None:
    """Breakout on the newest CLOSED bar only (so a signal fires once, not on every later bar)."""
    rng = opening_range(bars, orb_min)
    if rng is None or len(bars) <= orb_min:
        return None
    high, low = rng
    last, prev = bars[-1], bars[-2]
    if not (last.close > high >= prev.close):
        return None
    if last.volume < vol_mult * avg_volume(bars[:-1]):
        return None
    stop = max(low, (high + low) / 2)  # mid-range stop when the range is wide
    entry = last.close
    if entry - stop <= 0:
        return None
    target = entry + target_r * (entry - stop)
    return Signal(symbol, "ORB", tick_round(entry), tick_round(stop), tick_round(target),
                  f"closed above the {orb_min}-minute opening range high {high:.2f} on "
                  f"{last.volume / max(avg_volume(bars[:-1]), 1):.1f}x volume")


def vwap_reclaim_signal(symbol: str, bars: list[Bar], min_below: int = 3, vol_mult: float = 1.2,
                        target_r: float = 2.0, stop_lookback: int = 5) -> Signal | None:
    if len(bars) < min_below + 2:
        return None
    vw = vwap_series(bars)
    last = bars[-1]
    if not last.close > vw[-1]:
        return None
    below = bars[-1 - min_below:-1]
    if not all(b.close < v for b, v in zip(below, vw[-1 - min_below:-1])):
        return None
    if last.volume < vol_mult * avg_volume(bars[:-1]):
        return None
    stop = min(b.low for b in bars[-stop_lookback:])
    entry = last.close
    if entry - stop <= 0:
        return None
    target = entry + target_r * (entry - stop)
    return Signal(symbol, "VWAP reclaim", tick_round(entry), tick_round(stop), tick_round(target),
                  f"reclaimed VWAP {vw[-1]:.2f} after {min_below}+ minutes below it, on volume")


STRATEGIES = {"orb": orb_signal, "vwap": vwap_reclaim_signal}


def find_signal(symbol: str, bars: list[Bar], strategies: list[str], orb_min: int = 5,
                target_r: float = 2.0) -> Signal | None:
    for name in strategies:
        if name == "orb":
            sig = orb_signal(symbol, bars, orb_min=orb_min, target_r=target_r)
        elif name == "vwap":
            sig = vwap_reclaim_signal(symbol, bars, target_r=target_r)
        else:
            continue
        if sig:
            return sig
    return None


def position_size(entry: float, stop: float, risk_usd: float, max_value: float) -> int:
    risk = entry - stop
    if risk <= 0 or entry <= 0:
        return 0
    return max(0, min(math.floor(risk_usd / risk), math.floor(max_value / entry)))


@dataclass
class DayBook:
    """Today's trades and the hard limits (5 trades, stop after 3 losses by default)."""
    max_trades: int = 5
    max_losses: int = 3
    trades: list[dict] = field(default_factory=list)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.get("pnl") is not None and t["pnl"] < 0)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.get("pnl") is not None and t["pnl"] > 0)

    @property
    def pnl(self) -> float:
        return round(sum(t.get("pnl") or 0 for t in self.trades), 2)

    def can_trade(self) -> tuple[bool, str]:
        if self.losses >= self.max_losses:
            return False, f"{self.losses} losses today - done trading for the day"
        if len(self.trades) >= self.max_trades:
            return False, f"{len(self.trades)} trades taken - that's the daily limit"
        return True, ""

    def traded(self, symbol: str) -> bool:
        return any(t["symbol"] == symbol for t in self.trades)
