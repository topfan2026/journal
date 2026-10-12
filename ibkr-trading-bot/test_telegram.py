"""Check the Telegram setup and say exactly what's wrong (src.notify itself stays silent on purpose).

    python test_telegram.py
"""
import sys

import requests

from src.common import ENV_PATH, env_str


def main() -> int:
    if not ENV_PATH.exists():
        print(f"No .env file in {ENV_PATH.parent}\n"
              "Fix: copy .env.example to .env in this folder (PowerShell: copy .env.example .env), "
              "then put your Telegram token and chat id in it.")
        return 1
    token, chat = env_str("TELEGRAM_BOT_TOKEN"), env_str("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are empty in .env.\n"
              "Fix: open .env in Notepad and fill in both lines (no spaces or quotes), then save.")
        return 1
    print(f"Token: {token[:6]}…{token[-4:]}   Chat id: {chat}")

    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
    except requests.RequestException as exc:
        print(f"Can't reach Telegram ({type(exc).__name__}). Check your internet / firewall.")
        return 1
    if not me.get("ok"):
        print("Telegram rejected the TOKEN. Copy it again from @BotFather (it looks like 7712345678:AAH...).")
        return 1
    print(f"Token OK: your bot is @{me['result']['username']}")

    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": "Test: hello from your IBKR trading bot ✅"}, timeout=10).json()
    if r.get("ok"):
        print("SENT. Check Telegram on your phone.")
        return 0
    desc = r.get("description", "")
    print(f"Telegram refused the message: {desc}")
    if "chat not found" in desc or "bot can't initiate" in desc or "Forbidden" in desc:
        print(f"Fix: open Telegram, search @{me['result']['username']}, press START, then run this again. "
              "Also check the chat id is the number @userinfobot gave you.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
