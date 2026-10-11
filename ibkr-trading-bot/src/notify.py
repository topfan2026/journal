"""Fire-and-forget push notifications (Telegram, optional ntfy fallback). Never raises."""
from __future__ import annotations

import traceback

import requests

from src.common import LOGS_DIR, env_str, now_et

TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env_str("TELEGRAM_CHAT_ID")
NOTIFY_URL = env_str("NOTIFY_URL")


def _log_error(where: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (LOGS_DIR / "notify_errors.log").open("a", encoding="utf-8") as f:
            tb = traceback.format_exc()
            if TELEGRAM_BOT_TOKEN:
                tb = tb.replace(TELEGRAM_BOT_TOKEN, "<redacted>")  # requests errors include the URL
            f.write(f"{now_et().isoformat(timespec='seconds')} {where}\n{tb}\n")
    except Exception:
        pass


def notify(title: str, body: str, priority: str = "default") -> None:
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"*{title}*\n{body}", "parse_mode": "Markdown"}
            r = requests.post(url, data=payload, timeout=5)
            if r.status_code == 400:
                # Telegram rejects unbalanced Markdown (e.g. a "_" in a log line); resend as plain text.
                r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": f"{title}\n{body}"}, timeout=5)
            r.raise_for_status()
        except Exception:
            _log_error("telegram")
    if NOTIFY_URL:
        try:
            requests.post(NOTIFY_URL, data=body.encode("utf-8"),
                          headers={"Title": title.encode("ascii", "ignore").decode(), "Priority": priority},
                          timeout=5).raise_for_status()
        except Exception:
            _log_error("ntfy")
