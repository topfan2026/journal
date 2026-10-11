"""Shared paths, settings and file helpers.

Every path is anchored to the project folder, not the current directory. Windows Task
Scheduler starts tasks in C:\\Windows\\System32, so a bare Path("trades.csv") would write
files there.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")

RULES_PATH = PROJECT_DIR / "rules.json"
ENV_PATH = PROJECT_DIR / ".env"
TRADES_PATH = PROJECT_DIR / "trades.csv"
POSITIONS_PATH = PROJECT_DIR / "open_positions.json"
WATCHLIST_PATH = PROJECT_DIR / "watchlist.txt"
SAFETY_LOG_PATH = PROJECT_DIR / "safety-check-log.json"
LOGS_DIR = PROJECT_DIR / "logs"
DASHBOARD_DIR = PROJECT_DIR / "dashboard"

TRADES_HEADER = ["timestamp_iso", "symbol", "side", "size", "fill_price", "order_id", "status", "stop_price"]

PAPER_PORTS = {7497, 4002}
LIVE_PORTS = {7496, 4001}

load_dotenv(ENV_PATH)


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    return int(env_str(name, str(default)) or default)


def env_float(name: str, default: float) -> float:
    return float(env_str(name, str(default)) or default)


def env_bool(name: str, default: bool = False) -> bool:
    return env_str(name, str(default)).lower() in {"1", "true", "yes", "y"}


def check_paper_live_guard() -> str | None:
    """Return an abort message if PAPER_TRADING disagrees with IBKR_PORT, else None."""
    port = env_int("IBKR_PORT", 7497)
    paper = env_bool("PAPER_TRADING", True)
    if paper and port in LIVE_PORTS:
        return f"ABORT: PAPER_TRADING=true but IBKR_PORT={port} is a live port"
    if not paper and port in PAPER_PORTS:
        return f"ABORT: PAPER_TRADING=false but IBKR_PORT={port} is a paper port"
    return None


def now_et() -> datetime:
    return datetime.now(ET)


def ts() -> str:
    """Prefix for console lines: [HH:MM:SS ET]."""
    return now_et().strftime("[%H:%M:%S ET]")


def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def to_py(obj):
    """Convert numpy scalars/bools (and nested containers) to plain Python for json."""
    if isinstance(obj, dict):
        return {str(k): to_py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_py(v) for v in obj]
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except (ValueError, TypeError):
            pass
    return obj


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_et().isoformat(timespec="seconds"), **to_py(record)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def ensure_trades_csv() -> None:
    if not TRADES_PATH.exists():
        with TRADES_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(TRADES_HEADER)


def read_trades() -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    with TRADES_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_trade(row: dict) -> None:
    """Append one row to trades.csv. Retries once if the file is locked (e.g. open in Excel)."""
    ensure_trades_csv()
    values = [row.get(col, "") for col in TRADES_HEADER]
    for attempt in range(2):
        try:
            with TRADES_PATH.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(values)
            return
        except PermissionError:
            if attempt == 0:
                time.sleep(1)
            else:
                raise


def todays_buy_count(trades: list[dict] | None = None) -> int:
    today = now_et().date().isoformat()
    trades = read_trades() if trades is None else trades
    return sum(1 for r in trades if r.get("side") == "BUY" and r.get("timestamp_iso", "").startswith(today))


def load_positions() -> list[dict]:
    if not POSITIONS_PATH.exists():
        return []
    try:
        return json.loads(POSITIONS_PATH.read_text(encoding="utf-8")) or []
    except json.JSONDecodeError:
        return []


def save_positions(positions: list[dict]) -> None:
    """Atomic write: write a .tmp file, then os.replace over the real one."""
    tmp = POSITIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(to_py(positions), indent=2), encoding="utf-8")
    os.replace(tmp, POSITIONS_PATH)


def read_watchlist() -> list[str]:
    if not WATCHLIST_PATH.exists():
        return []
    out = []
    for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out
