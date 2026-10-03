"""Market Radar: a daily market-regime report sent to your Telegram bot.

    python market_radar.py print     build the report and print it
    python market_radar.py send      build it and send it to Telegram
    python market_radar.py chatid    show the chat id of whoever last messaged your bot

Data (free, no keys): Yahoo Finance daily closes and FRED (Federal Reserve) series.
Telegram: create a bot with @BotFather -> TELEGRAM_BOT_TOKEN; message your bot once, then
`chatid` (or the app's "Find my chat ID") -> TELEGRAM_CHAT_ID. The scheduler sends it at
RADAR_TIMES on RADAR_DAYS when RADAR_ENABLED=true.

What each line means
  SPY vs 200-MA        close / 200-day average - 1             (trend)
  RSI (14-day)         Wilder RSI of SPY                        (momentum)
  VIX, VIX z-score     VIX and its z-score over the last year   (fear vs normal)
  Liquidity strain     2Y Treasury yield - effective Fed Funds   (>0: market prices tighter money)
  Breadth              5-day rate of change of IWM/SPY (small caps vs the S&P 500: participation)
  VIX ROC              VIX change over 5 and 10 days (volatility acceleration)
  Credit / Junk        LQD/IEF and HYG/IEF vs their 200-day averages (corporate vs Treasuries)
  YC                   10Y - 2Y Treasury yield (yield curve)
  Cr10d                HYG/IEF change over 10 trading days
  VIX/VIX3M, SKEW      volatility term structure (>1 = stress) and tail-hedging demand
  Semi breadth         SMH/SPY vs its 200-day average (semis leading or lagging)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime

from config import env, env_bool

log = logging.getLogger("radar")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# --------------------------------------------------------------------------- data

def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo_closes(symbol: str, rng: str = "2y") -> list[float]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?range={rng}&interval=1d")
    data = json.loads(_get(url))
    result = data["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    return [c for c in closes if c is not None]


def fred_latest(series: str) -> float:
    rows = list(csv.reader(io.StringIO(_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}").decode())))
    for row in reversed(rows[1:]):
        try:
            return float(row[1])
        except (ValueError, IndexError):
            continue
    raise ValueError(f"FRED {series}: no data")


# --------------------------------------------------------------------------- maths

def sma(values: list[float], n: int) -> float:
    return sum(values[-n:]) / min(n, len(values))


def vs_ma(values: list[float], n: int = 200) -> float:
    """Percent above (+) or below (-) the n-day average."""
    return (values[-1] / sma(values, n) - 1) * 100


def rsi(values: list[float], n: int = 14) -> float:
    gains, losses = [], []
    for a, b in zip(values[:-1], values[1:]):
        gains.append(max(b - a, 0))
        losses.append(max(a - b, 0))
    avg_g, avg_l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


def zscore(values: list[float], n: int = 252) -> float:
    window = values[-n:]
    sd = statistics.pstdev(window)
    return 0.0 if sd == 0 else (values[-1] - statistics.mean(window)) / sd


def ratio(a: list[float], b: list[float]) -> list[float]:
    n = min(len(a), len(b))
    return [x / y for x, y in zip(a[-n:], b[-n:]) if y]


def pct_change(values: list[float], days: int) -> float:
    return (values[-1] / values[-1 - days] - 1) * 100


# --------------------------------------------------------------------------- report

def collect() -> dict:
    """Fetch everything; a missing piece becomes None instead of failing the whole report."""
    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            log.warning("[radar] %s %s failed: %s", fn.__name__, a, e)
            return None
    syms = ["SPY", "^VIX", "^VIX3M", "^SKEW", "IWM", "LQD", "HYG", "IEF", "SMH"]
    closes = {s: safe(yahoo_closes, s) for s in syms}
    fred = {s: safe(fred_latest, s) for s in ("DGS2", "DGS10", "DFF")}
    watch = [w.strip().upper() for w in (env("RADAR_WATCHLIST", "") or "").split(",") if w.strip()]
    watch_closes = {w: safe(yahoo_closes, w, "1y") for w in watch}
    return {"closes": closes, "fred": fred, "watch": watch_closes}


def metrics(data: dict) -> dict:
    c, f = data["closes"], data["fred"]
    m: dict = {}

    def have(*names):
        return all(c.get(n) and len(c[n]) > 30 for n in names)
    if have("SPY"):
        m["spy_ma"] = vs_ma(c["SPY"])
        m["rsi"] = rsi(c["SPY"])
    if have("^VIX"):
        m["vix"], m["vix_z"] = c["^VIX"][-1], zscore(c["^VIX"])
        m["vix_roc_5d"], m["vix_roc_10d"] = pct_change(c["^VIX"], 5), pct_change(c["^VIX"], 10)
    if have("^VIX", "^VIX3M"):
        m["vix_term"] = c["^VIX"][-1] / c["^VIX3M"][-1]
    if have("^SKEW"):
        m["skew"] = c["^SKEW"][-1]
    if have("IWM", "SPY"):
        m["breadth"] = pct_change(ratio(c["IWM"], c["SPY"]), 5)
    if have("LQD", "IEF"):
        m["credit"] = vs_ma(ratio(c["LQD"], c["IEF"]))
    if have("HYG", "IEF"):
        hy = ratio(c["HYG"], c["IEF"])
        m["junk"], m["cr10d"] = vs_ma(hy), pct_change(hy, 10)
    if have("SMH", "SPY"):
        m["semis"] = vs_ma(ratio(c["SMH"], c["SPY"]))
    if f.get("DGS2") is not None and f.get("DFF") is not None:
        m["liq"] = f["DGS2"] - f["DFF"]
    if f.get("DGS2") is not None and f.get("DGS10") is not None:
        m["yc"] = f["DGS10"] - f["DGS2"]
    m["watch"] = {w: (vs_ma(v, 50), pct_change(v, 5)) for w, v in data.get("watch", {}).items() if v and len(v) > 50}
    return m


def light(value: float | None, good: float, bad: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "⚪"
    v = value if higher_is_better else -value
    g, b = (good, bad) if higher_is_better else (-good, -bad)
    return "🟢" if v >= g else "🔴" if v <= b else "🟠"


def signals(m: dict) -> list[str]:
    out = []
    if m.get("spy_ma") is not None and m["spy_ma"] < 0:
        out.append("SPY below its 200-day average (trend break)")
    if m.get("vix_z") is not None and m["vix_z"] > 2:
        out.append("VIX spike (z > 2): fear well above normal")
    if m.get("vix_roc_5d") is not None and m["vix_roc_5d"] > 30:
        out.append("VIX up over 30% in 5 days: volatility accelerating")
    if m.get("breadth") is not None and m["breadth"] < -5:
        out.append("Small caps sharply lagging (IWM/SPY 5-day): narrow market")
    if m.get("vix_term") is not None and m["vix_term"] > 1:
        out.append("VIX above VIX3M (backwardation): near-term stress")
    if m.get("rsi") is not None and m["rsi"] > 70:
        out.append("SPY RSI over 70: overbought")
    if m.get("rsi") is not None and m["rsi"] < 30:
        out.append("SPY RSI under 30: oversold")
    if m.get("junk") is not None and m["junk"] < -3:
        out.append("Junk bonds breaking down vs Treasuries")
    if m.get("yc") is not None and m["yc"] < 0:
        out.append("Yield curve inverted (10Y < 2Y)")
    return out


def summary(m: dict) -> str:
    parts = []
    spy, vz = m.get("spy_ma"), m.get("vix_z")
    if spy is not None:
        trend = "Bull trend intact" if spy > 0 else "Trend broken"
        parts.append(f"{trend} - SPY is {'extended' if spy > 5 else ''} {abs(spy):.1f}% "
                     f"{'above' if spy >= 0 else 'below'} the 200-day MA".replace("  ", " "))
    if vz is not None:
        parts.append("with calm volatility" if vz < 0 else "with volatility above normal" if vz < 2
                     else "with a fear spike in volatility")
    text = " ".join(parts) + "." if parts else ""
    under = []
    if m.get("breadth") is not None:
        under.append("breadth is soft" if m["breadth"] < 0 else "breadth is healthy")
    if m.get("credit") is not None:
        under.append("credit is stable" if m["credit"] > -2 else "credit is weakening")
    if m.get("semis") is not None:
        under.append("semis are leading" if m["semis"] > 0 else "semis are lagging")
    if under:
        text += " Under the surface, " + ", ".join(under) + "."
    if m.get("liq") is not None:
        text += (f" Liquidity strain is {'elevated' if m['liq'] > 0.5 else 'easing' if m['liq'] < 0 else 'neutral'}"
                 f" (2Y - Fed Funds {m['liq']:+.2f})")
        if m["liq"] > 0.5:
            text += " - a tightening regime like 2000/2022, not a 1998-style easing backdrop."
        elif m["liq"] < 0:
            text += " - an easing backdrop, closer to 1998 than to 2000/2022."
        else:
            text += "."
        if spy is not None and spy > 0:
            text += (" Participation still looks constructive, but discipline matters more than chasing extension."
                     if spy > 5 else " Trend and participation look constructive.")
    return text.strip()


def regime(m: dict) -> str:
    n = len(signals(m))
    if m.get("spy_ma") is not None and m["spy_ma"] < 0 or n >= 3:
        return "🔴 RISK - defensive conditions"
    if n >= 1 or (m.get("liq") or 0) > 0.5 and (m.get("breadth") or 0) < -3:
        return "🟠 CAUTION - trend up, but warnings building"
    return "🟢 SAFE - bull trend intact"


def report(m: dict, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    f = lambda k, fmt: (format(m[k], fmt) if m.get(k) is not None else "n/a")  # noqa: E731
    lines = [f"Radar Intel · {now.strftime('%b %d, %I:%M %p')} {now.strftime('%Z')} 📡", ""]
    lines += [f"🔷 {f('spy_ma', '+.1f')}% SPY vs 200-MA", f"🔷 {f('rsi', '.1f')} RSI (14-day)",
              f"🔷 {f('vix', '.1f')} VIX Index", f"🔷 {f('vix_z', '+.2f')}σ VIX Z-Score",
              f"🔷 {f('vix_roc_5d', '+.1f')}% / {f('vix_roc_10d', '+.1f')}% VIX 5d / 10d change",
              f"🔷 {f('liq', '+.2f')} Liquidity Strain (2Y - Fed Funds)", ""]
    sysline = (f"Systemic: {light(m.get('breadth'), 0, -3)} Breadth {f('breadth', '+.1f')}% | "
               f"{light(m.get('credit'), 0, -2)} Credit {f('credit', '+.1f')}% | "
               f"{light(m.get('junk'), 0, -3)} Junk {f('junk', '+.1f')}% | "
               f"{light(m.get('yc'), 0.25, 0)} YC {f('yc', '+.2f')} | Cr10d {f('cr10d', '+.1f')}% | "
               f"VIX/VIX3M {f('vix_term', '.2f')} | SKEW {f('skew', '.0f')} | "
               f"{light(m.get('liq'), 0, 0.5, higher_is_better=False)} Liq {f('liq', '+.2f')} (2Y-FF)")
    lines += [sysline, ""]
    if m.get("semis") is not None:
        lines += [f"Semi breadth: {light(m['semis'], 0, -5)} SMH vs SPY {m['semis']:+.1f}% vs 200D "
                  f"({'semis leading the market' if m['semis'] > 0 else 'semis lagging the market'})", ""]
    sig = signals(m)
    lines += [f"Signals: {'none' if not sig else len(sig)} (core: {len(sig)} active)", f"Regime: {regime(m)}"]
    lines += [f"  ⚠️ {s}" for s in sig]
    lines += ["", "US Market: " + summary(m)]
    if m.get("watch"):
        lines += ["", "Watchlist (vs 50D | 5-day):"]
        for sym, (ma, wk) in sorted(m["watch"].items(), key=lambda kv: -kv[1][0]):
            lines.append(f"{light(ma, 0, -5)} {sym}: {ma:+.1f}% | {wk:+.1f}%")
    lines += ["", "Educational market overview, not financial advice."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- telegram

def telegram_send(text: str, token: str | None = None, chat_id: str | None = None) -> None:
    token = token or env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (Market Radar tab)")
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        reply = json.loads(r.read())
    if not reply.get("ok"):
        raise RuntimeError(f"Telegram refused the message: {reply.get('description')}")


def telegram_chat_id(token: str | None = None) -> str:
    token = token or env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("set TELEGRAM_BOT_TOKEN first")
    updates = json.loads(_get(f"https://api.telegram.org/bot{token}/getUpdates"))
    chats = [u.get("message", {}).get("chat", {}) for u in updates.get("result", [])]
    chats = [c for c in chats if c.get("id")]
    if not chats:
        raise RuntimeError("no messages yet - open your bot in Telegram, send it 'hi', then try again")
    c = chats[-1]
    return f"{c['id']} ({c.get('first_name') or c.get('title') or c.get('username') or 'chat'})"


def build() -> str:
    return report(metrics(collect()))


def send() -> str:
    text = build()
    telegram_send(text)
    return text


# --------------------------------------------------------------------------- schedule (used by the scheduler)

def due(now: datetime, sent: set[str]) -> str | None:
    """The RADAR_TIMES slot that is due now (within its first 15 minutes) and not yet sent, if any."""
    from datetime import timedelta
    if not env_bool("RADAR_ENABLED", False):
        return None
    from live import DAYS
    allowed: set[int] = set()
    for part in (env("RADAR_DAYS", "mon-fri") or "mon-fri").lower().replace(" ", "").split(","):
        if "-" in part:
            a, b = (DAYS.index(x[:3]) for x in part.split("-"))
            allowed.update(range(a, b + 1))
        elif part:
            allowed.add(DAYS.index(part[:3]))
    if now.weekday() not in allowed:
        return None
    for slot in (env("RADAR_TIMES", "06:00,13:15") or "").split(","):
        slot = slot.strip()
        if not slot:
            continue
        h, mi = (int(x) for x in slot.split(":"))
        at = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        key = f"{now:%Y-%m-%d} {slot}"
        if at <= now < at + timedelta(minutes=15) and key not in sent:
            return key
    return None


def radar_loop(stop_event, sleep=None) -> None:
    """Runs inside the scheduler: sends the report at RADAR_TIMES (also while a stream is live)."""
    from config import reload_env
    sent: set[str] = set()
    while not stop_event.is_set():
        try:
            reload_env()
            key = due(datetime.now(), sent)
            if key:
                sent.add(key)
                send()
                log.info("[radar] Market Radar sent to Telegram (%s)", key)
        except Exception as e:
            log.warning("[radar] couldn't send the Market Radar: %s", e)
        stop_event.wait(30)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from config import reload_env
    reload_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["print", "send", "chatid"])
    args = ap.parse_args(argv)
    try:
        if args.command == "chatid":
            print("your chat id:", telegram_chat_id())
        elif args.command == "print":
            print(build())
        else:
            print(send())
            print("\nsent to Telegram")
    except Exception as e:
        print(f"radar failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
