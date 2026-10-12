"""IBKR Trading Bot desktop app: a live window onto the bot and your account's performance.

    python app.py            (the desktop shortcut runs this via launch.py)

Serves a page on http://127.0.0.1:18765 (this PC only; the next free port if that's taken) and opens it in your browser.
Its IBKR connection is READ-ONLY: the app can't place orders. Trading stays with cycle.py.
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import defaultdict, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.common import (ET, PAUSE_PATH, PROJECT_DIR, SAFETY_LOG_PATH, WATCHLIST_PATH, env_bool, env_float, env_int, env_str,
                        load_positions, load_rules, now_et, read_trades, read_watchlist)

APP_SIGNATURE = "ibkr-trading-bot-app"  # lets us tell our app apart from other programs on the port
FIRST_PORT = 18765  # tries this and the next 19 ports; set APP_PORT in .env to change
APP_CLIENT_ID = 7
UI_PATH = PROJECT_DIR / "app_ui.html"
ICON_PATH = PROJECT_DIR / "icon.ico"
WINDOW_PROFILE = PROJECT_DIR / ".appwindow"  # Edge profile just for the app window
TOKEN = secrets.token_urlsafe(16)  # blocks other websites from POSTing actions to localhost

_lock = threading.Lock()
_live: dict = {"connected": False, "error": "starting…"}
_jobs: dict = {}


# ------------------------------------------------------------------ IBKR (main thread)

def ibkr_loop() -> None:
    """Keep a read-only TWS connection and snapshot account data every few seconds."""
    from ib_async import IB

    ib = IB()
    host, port = env_str("IBKR_HOST", "127.0.0.1"), env_int("IBKR_PORT", 7497)
    while True:
        if not ib.isConnected():
            try:
                ib.connect(host, port, clientId=APP_CLIENT_ID, readonly=True, timeout=5)
            except Exception as exc:
                with _lock:
                    _live.clear()
                    _live.update(connected=False, error=f"Waiting for TWS on port {port} — open TWS and log in "
                                                         f"({type(exc).__name__})")
                time.sleep(5)
                continue
        try:
            snapshot = ibkr_snapshot(ib)
            with _lock:
                _live.clear()
                _live.update(snapshot)
            ib.sleep(3)
        except Exception as exc:
            with _lock:
                _live.update(connected=False, error=repr(exc))
            try:
                ib.disconnect()
            except Exception:
                pass
            time.sleep(3)


def ibkr_snapshot(ib) -> dict:
    vals = {}
    for v in ib.accountValues():
        if v.currency in ("USD", "BASE") and v.tag in {"NetLiquidation", "TotalCashValue", "BuyingPower",
                                                        "UnrealizedPnL", "RealizedPnL", "GrossPositionValue"}:
            vals.setdefault(v.tag, float(v.value))
    portfolio = [{"symbol": p.contract.symbol, "qty": p.position, "avg_cost": p.averageCost,
                  "price": p.marketPrice, "value": p.marketValue, "unrealized": p.unrealizedPNL}
                 for p in ib.portfolio() if p.position]
    fills = []
    for f in sorted(ib.fills(), key=lambda f: f.time):
        ex = f.execution
        fills.append({"time": f.time.astimezone(ET).isoformat(timespec="seconds"), "symbol": f.contract.symbol,
                      "side": "BUY" if ex.side == "BOT" else "SELL", "qty": ex.shares, "price": ex.price,
                      "client": ex.clientId,
                      "commission": f.commissionReport.commission if f.commissionReport else 0.0})
    return {"connected": True, "error": "", "accounts": ib.managedAccounts(), "values": vals,
            "portfolio": portfolio, "fills": fills, "updated": now_et().strftime("%H:%M:%S")}


# ------------------------------------------------------------------ files -> state

def performance(rows: list[dict]) -> dict:
    """FIFO P&L for any list of {timestamp_iso, symbol, side, size, fill_price, stop_price?} rows."""
    from compute_perf import aggregate, pair_trades
    closed = pair_trades(rows)
    today = now_et().date().isoformat()
    equity, total = [], 0.0
    for c in sorted(closed, key=lambda c: c["exit_time"]):
        total += c["pnl"]
        equity.append({"t": c["exit_time"], "v": round(total, 2)})
    return {"all": aggregate(closed), "today": aggregate([c for c in closed if c["exit_time"].startswith(today)]),
            "closed": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()} for c in closed[-50:]][::-1],
            "equity": equity}


def account_performance(fills: list[dict]) -> dict:
    """Today's round trips across the WHOLE account (your own TWS trades + the bot's)."""
    rows = [{"timestamp_iso": f["time"], "symbol": f["symbol"], "side": f["side"], "size": f["qty"],
             "fill_price": f["price"]} for f in fills]
    perf = performance(rows)
    by_sym: dict[str, float] = defaultdict(float)
    for c in perf["closed"]:
        by_sym[c["symbol"]] += c["pnl"]
    perf["by_symbol"] = sorted(({"symbol": s, "pnl": round(v, 2)} for s, v in by_sym.items()), key=lambda r: -r["pnl"])
    perf["commissions"] = round(sum(f["commission"] or 0 for f in fills), 2)
    return perf


def recent_events(limit: int = 60) -> list[dict]:
    if not SAFETY_LOG_PATH.exists():
        return []
    with SAFETY_LOG_PATH.open(encoding="utf-8") as f:
        lines = deque(f, maxlen=2000)
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out[-limit:][::-1] if limit else out


def watchlist_verdicts() -> list[dict]:
    """Each watchlist ticker with the bot's latest verdict today (why it bought or skipped)."""
    today = now_et().date().isoformat()
    latest: dict[str, dict] = {}
    for e in recent_events(limit=0):
        if e.get("symbol") and str(e.get("ts", "")).startswith(today) and e.get("event") in {"evaluate", "entry", "entry_skip"}:
            latest[e["symbol"]] = e
    notes = {}
    if WATCHLIST_PATH.exists():
        for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#") and "#" in line:
                sym, note = line.split("#", 1)
                notes[sym.strip()] = note.strip()
    out = []
    for sym in read_watchlist():
        e = latest.get(sym, {})
        if e.get("event") == "entry":
            verdict, detail = "BOUGHT", f"{e.get('qty')} @ {e.get('price'):.2f}, stop {e.get('stop'):.2f}"
        elif e.get("event") == "evaluate":
            verdict = "PASS" if e.get("passed") else "SKIP"
            detail = "; ".join(r for r in e.get("reasons", []) if "FAIL" in r) or "; ".join(e.get("reasons", []))
        elif e.get("event") == "entry_skip":
            verdict, detail = "SKIP", e.get("reason", "")
        else:
            verdict, detail = "WAITING", "not evaluated yet today"
        out.append({"symbol": sym, "gap": notes.get(sym, ""), "verdict": verdict, "detail": detail})
    return out


_sched_cache = {"at": 0.0, "value": None}


def schedule_status() -> dict:
    if sys.platform != "win32":
        return {"installed": None, "detail": "Task Scheduler is Windows-only (use cron on Mac/Linux)"}
    if time.monotonic() - _sched_cache["at"] < 60 and _sched_cache["value"]:
        return _sched_cache["value"]
    r = subprocess.run(["schtasks", "/query", "/tn", "HT_Cycle", "/fo", "LIST"], capture_output=True, text=True)
    if r.returncode != 0:
        value = {"installed": False, "detail": "Not scheduled — click “Install schedule”"}
    else:
        info = dict(l.split(":", 1) for l in r.stdout.splitlines() if ":" in l)
        value = {"installed": True, "detail": f"{info.get('Status', '').strip()} · next run {info.get('Next Run Time', '').strip()}"}
    _sched_cache.update(at=time.monotonic(), value=value)
    return value


def build_state() -> dict:
    from cycle import time_gate
    rules = load_rules()
    with _lock:
        live = json.loads(json.dumps(_live, default=str))
    positions = {p["symbol"]: p for p in load_positions()}
    for row in live.get("portfolio", []):
        bot = positions.get(row["symbol"])
        row["bot"] = bool(bot)
        if bot:
            r = bot["R"] or 1
            row.update(stop=bot["stop"], entry=bot["entry_price"], state=bot["state"],
                       r_now=round((row["price"] - bot["entry_price"]) / r, 2) if row.get("price") else None)
    gate = time_gate(now_et(), rules)
    return {
        "now": now_et().strftime("%a %b %d, %H:%M:%S ET"),
        "market": gate,
        "paused": PAUSE_PATH.exists(),
        "paper": env_bool("PAPER_TRADING", True),
        "port": env_int("IBKR_PORT", 7497),
        "strategy": rules.get("strategy_name", ""),
        "rules": rules,
        "risk_env": {"portfolio": env_float("PORTFOLIO_VALUE_USD", 25000),
                     "max_trade_usd": env_float("MAX_TRADE_SIZE_USD", 2500),
                     "risk_pct": env_float("MAX_RISK_PER_TRADE_PCT", float(rules["risk"]["max_risk_per_trade_pct"])),
                     "max_trades_per_day": env_int("MAX_TRADES_PER_DAY", 5)},
        "live": live,
        "bot_positions": list(positions.values()),
        "bot_perf": performance(read_trades()),
        "account_perf": account_performance(live.get("fills", [])),
        "watchlist": watchlist_verdicts(),
        "watchlist_time": datetime.fromtimestamp(WATCHLIST_PATH.stat().st_mtime, ET).strftime("%H:%M ET %b %d")
        if WATCHLIST_PATH.exists() else None,
        "events": recent_events(),
        "schedule": schedule_status(),
        "jobs": dict(_jobs),
    }


# ------------------------------------------------------------------ actions

ACTIONS = {
    "scan": ["morning_prefilter.py"],
    "scan_test": ["morning_prefilter.py", "--min-gap", "1.0"],
    "cycle": ["cycle.py"],
    "summary": ["compute_perf.py"],
    "schedule": ["setup_schedule.py"],
}


def run_action(name: str) -> str:
    if name == "pause":
        PAUSE_PATH.write_text("paused from the app\n", encoding="utf-8")
        return "Paused: no new trades. Open trades are still managed."
    if name == "resume":
        PAUSE_PATH.unlink(missing_ok=True)
        return "Resumed."
    if name not in ACTIONS:
        return f"unknown action {name}"
    if _jobs.get(name, {}).get("running"):
        return f"{name} is already running"

    def worker():
        _jobs[name] = {"running": True, "output": "", "started": now_et().strftime("%H:%M:%S")}
        try:
            r = subprocess.run([sys.executable, str(PROJECT_DIR / ACTIONS[name][0]), *ACTIONS[name][1:]],
                               cwd=PROJECT_DIR, capture_output=True, text=True, timeout=600)
            out = (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            out = "timed out after 10 minutes"
        _jobs[name] = {"running": False, "output": out[-4000:], "finished": now_et().strftime("%H:%M:%S")}
        _sched_cache["at"] = 0.0

    threading.Thread(target=worker, daemon=True).start()
    return f"Started {name}"


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = UI_PATH.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            self._send(200, html.encode(), "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._send(200, ICON_PATH.read_bytes(), "image/x-icon")
        elif self.path == "/api/ping":
            self._send(200, json.dumps({"app": APP_SIGNATURE}).encode(), "application/json")
        elif self.path == "/api/state":
            try:
                body = json.dumps(build_state(), default=str).encode()
                self._send(200, body, "application/json")
            except Exception as exc:
                self._send(500, json.dumps({"error": repr(exc)}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN or not self.path.startswith("/api/action/"):
            self._send(403, b"forbidden", "text/plain")
            return
        msg = run_action(self.path.rsplit("/", 1)[-1])
        self._send(200, json.dumps({"message": msg}).encode(), "application/json")


class AppServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second program bind a port that's already in use, so the
    # browser could end up talking to someone else's server. Require the port to be truly free.
    allow_reuse_address = sys.platform != "win32"


def is_our_app(port: int) -> bool:
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return json.loads(r.read()).get("app") == APP_SIGNATURE
    except Exception:
        return False


def find_app_browser() -> str | None:
    """Edge (on every Windows 10/11 PC) or Chrome, which can show a page as a standalone app window."""
    import os
    import shutil
    candidates = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                           Path(base) / "Google/Chrome/Application/chrome.exe"]
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return None


def open_window(url: str):
    """Open the app in its own window (no tabs or address bar). Returns the window's process,
    or None if it fell back to a normal browser tab."""
    browser = find_app_browser()
    if browser:
        try:
            return subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={WINDOW_PROFILE}",
                                     "--window-size=1400,900", "--no-first-run", "--no-default-browser-check",
                                     "--disable-sync"])  # the app window is not a browsing profile; never sync it
        except OSError:
            pass
    webbrowser.open(url)
    return None


def quit_when_window_closes(proc) -> None:
    started = time.monotonic()
    proc.wait()
    # If an app window from an earlier run was still open, Edge hands the new one to it and this
    # process exits at once. Then keep serving (the open window still needs us) instead of quitting.
    if time.monotonic() - started > 5:
        import os
        os._exit(0)


def log_to_file_if_windowless() -> None:
    """Under pythonw.exe (no console window) print() goes nowhere; send it to logs/app.log instead."""
    if sys.stdout is None or sys.stderr is None:
        from src.common import LOGS_DIR
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        f = open(LOGS_DIR / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f


def main() -> int:
    log_to_file_if_windowless()
    first = env_int("APP_PORT", FIRST_PORT)
    server = None
    for port in range(first, first + 20):
        if is_our_app(port):
            print(f"The app is already running — showing http://127.0.0.1:{port}")
            open_window(f"http://127.0.0.1:{port}")
            return 0
        try:
            server = AppServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            print(f"Port {port} is used by another program, trying the next one…")
    if server is None:
        print(f"No free port between {first} and {first + 19}. Set APP_PORT=... in .env to another number.")
        return 1
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    print(f"{now_et():%Y-%m-%d %H:%M:%S} IBKR Trading Bot app running at {url}. "
          f"Closing the app window quits it; the scheduled bot keeps trading either way.")
    proc = open_window(url)
    if proc is not None:
        threading.Thread(target=quit_when_window_closes, args=(proc,), daemon=True).start()
    try:
        ibkr_loop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
