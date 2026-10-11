"""Archive old logs so the bot can run for months. Safe to run any time; exits 0 with nothing to do."""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta

from src.common import ET, LOGS_DIR, SAFETY_LOG_PATH, TRADES_HEADER, TRADES_PATH, now_et

KEEP_TRADE_DAYS = 90
MAX_SAFETY_LOG_BYTES = 5 * 1024 * 1024


def main() -> int:
    today = now_et().date()
    archive = LOGS_DIR / "archive"
    moved = 0

    if LOGS_DIR.exists():
        for f in LOGS_DIR.iterdir():
            if not f.is_file() or f.suffix not in {".log", ".jsonl"}:
                continue
            day = datetime.fromtimestamp(f.stat().st_mtime, ET).date()
            if day < today:
                dest = archive / day.isoformat()
                dest.mkdir(parents=True, exist_ok=True)
                os.replace(f, dest / f.name)
                moved += 1

    if TRADES_PATH.exists():
        cutoff = (today - timedelta(days=KEEP_TRADE_DAYS)).isoformat()
        with TRADES_PATH.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        old = [r for r in rows if r["timestamp_iso"][:10] < cutoff]
        if old:
            archive.mkdir(parents=True, exist_ok=True)
            for path, subset in ((archive / f"trades_{today:%Y%m%d}.csv", old),
                                 (TRADES_PATH.with_suffix(".csv.tmp"), [r for r in rows if r not in old])):
                with path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=TRADES_HEADER, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(subset)
            os.replace(TRADES_PATH.with_suffix(".csv.tmp"), TRADES_PATH)
            moved += 1

    if SAFETY_LOG_PATH.exists() and SAFETY_LOG_PATH.stat().st_size > MAX_SAFETY_LOG_BYTES:
        archive.mkdir(parents=True, exist_ok=True)
        os.replace(SAFETY_LOG_PATH, archive / f"{today.isoformat()}_{SAFETY_LOG_PATH.name}")
        moved += 1

    print(f"Rotated {moved} files to logs/archive/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
