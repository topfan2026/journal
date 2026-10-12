"""yfinance bar fetching (screening and filter data only; IBKR handles execution)."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from src.common import ET


def yahoo_symbol(ibkr_symbol: str) -> str:
    """IBKR "BRK B" -> Yahoo "BRK-B"."""
    return ibkr_symbol.replace(" ", "-")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def daily_bars(symbol: str, period: str = "1y") -> pd.DataFrame:
    df = yf.Ticker(yahoo_symbol(symbol)).history(period=period, interval="1d", auto_adjust=True)
    df = _clean(df)
    if not df.empty and df.index.tz is not None:
        df.index = df.index.tz_convert(ET)
    return df


def intraday_bars(symbol: str, period: str = "30d", interval: str = "5m") -> pd.DataFrame:
    """Intraday bars incl. pre/post market, ET index. yfinance keeps 60 days of 5m and 7 days of 1m history."""
    df = yf.Ticker(yahoo_symbol(symbol)).history(period=period, interval=interval, prepost=True, auto_adjust=True)
    df = _clean(df)
    if df.empty:
        return df
    df.index = df.index.tz_convert(ET) if df.index.tz is not None else df.index.tz_localize(ET)
    return df
