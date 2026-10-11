# ibkr-trading-bot

An automated **paper-trading** bot for Interactive Brokers, built from the "AI trading bot with Claude Code + IBKR"
tutorial (Part 2). It scans the S&P 500 for gappers, applies the **Trend Join Long** rules from `rules.json`,
places orders through TWS / IB Gateway, manages stops (0.75R partial, breakeven at 1R, 5-minute swing-low trail),
flattens everything at 15:51 ET, sends Telegram alerts and builds an HTML dashboard.

> Paper trade for at least 2 weeks before you consider live money. This is a starting point, not a money printer.

## Setup (Windows)

1. **TWS:** log into your paper account → *File > Global Configuration > API > Settings*:
   enable *ActiveX and Socket Clients*, *Allow connections from localhost only*, Socket Port **7497**,
   untick *Read-Only API*, make sure `127.0.0.1` is a Trusted IP. Restart TWS.
2. **Python 3.12+** in this folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
   Edit `.env` (portfolio size, Telegram token/chat id; see below).
3. **Connection test:** `python test_connect.py` → `Connected: True  Accounts: ['DU…']`
4. **Wiring test (market hours):** `python buy_one.py` then `python close_one.py` (1 share of MU, paper).
5. **Dry run:** `python bot.py --symbol NVDA --check-only`
6. **Scanner:** `python morning_prefilter.py --dry-run` (use `--min-gap 1.0` on a quiet day), then without `--dry-run`.
7. **Cycle:** `python cycle.py` (exits instantly outside 10:00–16:00 ET on weekdays, which is correct).
8. **Telegram:** message @BotFather `/newbot` → token; @userinfobot → chat id; put both in `.env`, then
   `python -c "from src.notify import notify; notify('Test', 'Hello from IBKR bot')"`
9. **Schedule everything:** `python setup_schedule.py` (11 tasks, no admin). Undo with `python cleanup_schedule.py`.
10. **Desktop shortcut:** `python make_desktop_shortcut.py` (see below).

## Desktop shortcut ("log in to the app")

`python make_desktop_shortcut.py` puts an **IBKR Trading Bot** shortcut on your desktop. Double-clicking it runs
`launch.py`, which:

1. opens TWS (or IB Gateway) if it isn't already running. It looks in `C:\Jts\...`; set `TWS_PATH=` in `.env` if yours is elsewhere,
2. waits while **you log in** in TWS's own login window (your IBKR password is never stored by the bot),
3. waits for the API port, runs the connection test, and
4. opens the dashboard.

On a Mac it creates `IBKR Trading Bot.command`, and on Linux it creates a `.desktop` launcher.

## Files

| File | Role |
|---|---|
| `rules.json` | The strategy: filters, time windows, exit ladder, risk. Edit values here, not in code. |
| `cycle.py` | The brain, run every 5 min: time gate → reconcile stop-outs → manage → force-close / entries |
| `morning_prefilter.py` | yfinance S&P 500 gap scan → `watchlist.txt` (top 20) |
| `trade.py` | Order executor, a separate process with `IBKR_EXEC_CLIENT_ID`, logs to `trades.csv` |
| `bot.py` + `strategy.py` | Single-symbol dev tool (time gate + already-held check only) |
| `compute_perf.py` | Daily summary (JSON + Telegram) and `dashboard/index.html` with R-multiple histogram |
| `rotate_logs.py` | Archives old logs, keeps 90 days of `trades.csv` |
| `setup_schedule.py` / `cleanup_schedule.py` | Windows Task Scheduler install / uninstall |
| `launch.py` / `make_desktop_shortcut.py` | Desktop shortcut: log in to TWS, check the connection, open the dashboard |
| `src/filters.py` | Pure logic: D1–D3, I1–I3, RVOL, swing lows, sizing (unit tested) |
| `src/ibkr_client.py` | ib_async wrapper: market orders, GTC protective stops, modify/cancel |

Run the tests with `pip install pytest && python -m pytest tests`.

## What I changed from the tutorial's prompts (and why)

Reviewing the prompts turned up several issues that would cause real problems. The code here fixes them:

| Issue in the original design | Fix |
|---|---|
| Relative paths (`Path("watchlist.txt")`) — Task Scheduler starts tasks in `C:\Windows\System32`, so files land there | All paths anchored to the project folder |
| Breakeven (1R) checked before the partial (0.75R): a stock jumping straight past 1R never banks the partial | Partial checked first; both can fire in one cycle |
| Stop orders filled by IBKR were never written to `trades.csv`, so the daily summary and dashboard missed every stop-out | Stop fills logged as `SELL … StopFilled` rows |
| `trade.py` wrote UTC timestamps but "today" is counted by ET date | ET timestamps throughout |
| After a partial, the stop could be larger than the position (a triggered stop would open a short) | Stop is resized **before** the partial sell |
| Stops were cancel-then-replace (a moment with no stop) | Stops are modified in place; GTC, so a crash never leaves a position naked overnight |
| A market order still working when `trade.py` times out could fill with no stop | Cycle checks IBKR's actual position after each buy, and adopts any of today's bot BUYs that have no stop |
| Prefilter before the open used yesterday's bar as "today" and reported yesterday's gaps | Bars not dated today are counted as `stale` and skipped |
| "Above today's high" compared with a high that already includes the current price, so it could never pass | Compared against the high of *completed* 5-minute bars |
| FIFO pairing by row breaks with partial exits | FIFO by share quantity |
| Telegram rejects messages with stray Markdown characters (e.g. `_`) | Retries as plain text; bot token redacted from error logs |
| Cycle trades yesterday's `watchlist.txt` if the prefilter fails | Entries are skipped unless the watchlist is from today |

The bot also enforces `max_concurrent_positions` and `MAX_TRADE_SIZE_USD`, and its paper/live guard also covers IB Gateway ports (4002/4001).

## Known limitations

- **Market holidays / early closes** aren't in a calendar. On a holiday there are no bars dated today, so no entries happen.
  On 1 pm early-close days the 15:51 force-close is too late: flatten manually or disable `HT_Cycle` that day.
- yfinance 5-minute data can lag a few minutes and is used for filters and the swing-low trail. Orders go through IBKR.
- Free paper accounts get **delayed** IBKR quotes (`reqMarketDataType(3)`), so the bot falls back to yfinance when IBKR has no price.
- `outsideRth=True` on market orders is accepted but has no effect: IBKR only fills market orders in regular hours.
- `setup_schedule.py` converts ET to your local time when you run it. Re-run it if your timezone's daylight-saving dates differ from New York's.
- Refresh `src/sp500_tickers.py` every 2–3 months (snapshot: 503 tickers, 2026-10-11).

## Mac / Linux scheduling (cron, times in ET)

```
CRON_TZ=America/New_York
25 9 * * 1-5        cd /path/to/ibkr-trading-bot && .venv/bin/python rotate_logs.py
55 9 * * 1-5        cd /path/to/ibkr-trading-bot && .venv/bin/python morning_prefilter.py
25,55 10-12 * * 1-5 cd /path/to/ibkr-trading-bot && .venv/bin/python morning_prefilter.py
*/5 10-15 * * 1-5   cd /path/to/ibkr-trading-bot && .venv/bin/python cycle.py
5 16 * * 1-5        cd /path/to/ibkr-trading-bot && .venv/bin/python compute_perf.py
```
For a headless VPS use IB Gateway (paper port 4002) and set `IBKR_PORT=4002`.
