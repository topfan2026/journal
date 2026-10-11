"""Run trade.py as a subprocess and parse its RESULT line."""
from __future__ import annotations

import json
import subprocess
import sys

from src.common import PROJECT_DIR


def run_trade(symbol: str, side: str, size: int, stop_price: float | None = None, timeout: int = 30) -> tuple[dict | None, str]:
    cmd = [sys.executable, str(PROJECT_DIR / "trade.py"), "--symbol", symbol, "--side", side, "--size", str(int(size))]
    if stop_price is not None:
        cmd += ["--stop-price", f"{stop_price:.4f}"]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # subprocess.run kills the child on timeout
        return None, f"trade.py timed out after {timeout}s\n{exc.stdout or ''}"
    output = (proc.stdout or "") + (proc.stderr or "")
    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT "):])
    return result, output
