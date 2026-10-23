# ibkr-trading-bot

An automated **paper-trading** bot for Interactive Brokers, built from the "AI trading bot with Claude Code + IBKR"
tutorial (Part 2). It scans the S&P 500 for gappers, applies the **Trend Join Long** rules from `rules.json`,
places orders through TWS / IB Gateway, manages stops (0.75R partial, breakeven at 1R, 5-minute swing-low trail),
flattens everything at 15:51 ET, sends Telegram alerts and builds an HTML dashboard.

> Paper trade for at least 2 weeks before you consider live money. This is a starting point, not a money printer.

## Setup (Windows)

0. **Easiest:** double-click `SETUP.bat` in this folder. It does steps 2, 8 (Telegram settings), 9 and 10 for you.
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
10. **Desktop app:** `python make_desktop_shortcut.py`, then double-click **IBKR Trading Bot** on your desktop (see below).

## The desktop app

`python make_desktop_shortcut.py` puts an **IBKR Trading Bot** shortcut on your desktop. Double-click it and:

1. TWS opens if it isn't already running, so you can **log in** to your paper account (TWS's own login: the bot never
   stores your password). It looks in `C:\Jts\...`; set `TWS_PATH=` in `.env` if yours is elsewhere.
2. The **app** opens in its own window (an Edge app window: no tabs or address bar, its own taskbar icon), served
   from `http://127.0.0.1:18765` on this PC only. Close the window to quit the app; the scheduled bot keeps trading
   either way. The shortcut is also in the Start menu (right-click > Pin to taskbar). App messages go to `logs/app.log`.

The app refreshes every 5 seconds and shows:

| Section | What you see |
|---|---|
| Status bar | Paper/live, TWS connected + account, market phase, bot active/paused |
| Numbers | Net liquidation, today's account P&L, your round trips today, bot all-time P&L, win rate, profit factor, avg R |
| Open positions | Everything in the account; bot trades marked **BOT** with their current stop and R |
| Today's watchlist | Each gapper and the bot's verdict: BOUGHT / SKIP (with the failed filter) / WAITING |
| My trades today | **Every fill in the account**, including trades you place yourself in TWS, with realized P&L per symbol |
| Bot performance | Equity curve and every closed bot trade with its R-multiple |
| Bot activity | Every decision the bot made, newest first |

Buttons: **Pause / Resume** (paused = no new entries; open trades keep their stops managed), **Scan now**,
**Test scan (1%)**, **Run cycle now**, **Daily summary**, **Install schedule**.

The app's TWS connection is **read-only** (client id 7), so it can't place orders. Its buttons are protected by a
per-session token, so other websites can't trigger them.

## Strategies

The app's **Strategies** panel lists every strategy with an on/off switch. Switched-on strategies paper trade
together; every trade is tagged with its strategy, and the performance view can be filtered per strategy.

| Template | Buys when |
|---|---|
| Trend Join Long | the original six filters pass (settings live in `rules.json`) |
| Opening Range Breakout | a fresh break above the first 5/15/30 minutes' high |
| EMA Cross | the fast EMA crosses above the slow EMA (5-minute bars) |
| Price crosses EMA | a 5-minute bar closes back above the EMA |
| EMA Bounce | in an uptrend, price touches the EMA and then takes out the last bar's high |
| Premarket High/Low Break (1-min) | long: the 2nd one-minute candle closes above the premarket high (stop below that candle's low); short: the mirror image below the premarket low |
| Custom (build your own) | every condition you set is true on the candle that just closed (see below) |
| HT_VWAP_Reclaim_Long | HumbledTrader: a VWAP reclaim on a volume push, or a pullback to VWAP as selling dries up; stop below the pullback low, never on VWAP |
| HT_BuyTheDip_Support | HumbledTrader: a stock that ran up pulls back to your marked support (or the auto breakout level) and stops making new lows; stop 10-15¢ below support |

Every new strategy has: stocks to watch (scanner gappers or your own ticker list), optional filters (gap, relative
volume, VWAP, daily uptrend), its own entry window, stop rule, partial / breakeven / full take-profit / trailing
exits, risk per trade and max trades per day. New strategies start **off**. Global limits (max open positions,
position size cap, `MAX_TRADES_PER_DAY`, the 15:51 force-close) apply to all of them.

**Custom builder:** pick *Custom (build your own)* → ＋ Add strategy → Edit. Under **Entry rules** stack up to 8
conditions of the form `<value> <is above | is below | crosses above | crosses below> [factor ×] <value>`. Values:
candle open/high/low/close/volume, previous candle, EMA n, SMA n, VWAP, RSI n, average volume n, high/low of day,
today's open, premarket high/low, opening range high/low (n minutes), yesterday's high/low/close, or a number.
Choose long or short, 1- or 5-minute candles, and the stop (signal candle, last N candles, day low/high, VWAP,
EMA N or N %). "Only a new signal" skips entries when the conditions were already true a candle earlier. The
bot's reasons on the trade chart show every condition with its values.

**Setup Finder:** the 🔎 section under Strategies backtests a playbook of classic intraday setups (ORB, premarket
break, VWAP reclaim / rejection, HOD / LOD break, EMA 9 pullback, red-to-green, yesterday's-high break, EMA cross,
HT_VWAP_Reclaim_Long) and your own strategies on the stocks and days you choose. It replays the market candle by
candle through the bot's own entry code (no look-ahead: the forming candle only shows its open), fills at the next
open with slippage, and simulates the bot's exits. Ranked by average R weighted by trade count; **Paper trade it**
adds a setup to Strategies, switched on. Data: Yahoo (5-minute bars ≈ 60 days, 1-minute ≈ 7 days).

**Shorts:** strategies can sell short (the premarket breakdown, and custom strategies set to Short). Shorts are mirrored longs: buy-stop above
the entry placed right after the fill, partial cover / breakeven / trailing above 5-minute swing highs, the same risk
sizing, end-of-day cover, and P&L / R counted flat-to-flat. Paper accounts don't model real borrow availability.

**Timing:** the cycle runs every minute; 5-minute strategies act only on 5-minute marks, 1-minute strategies every
minute (1-minute bars from Yahoo, which can lag slightly). Re-install the schedule after updating.
Settings are stored in `strategies.json` (kept by updates).

## Trade charts

Click any trade, open position, watchlist stock or fill in the app to open its chart (TradingView Lightweight
Charts™, bundled in `vendor/`, Apache-2.0): 5-minute candles with volume, EMA 9/20/50 and VWAP (toggle each),
key levels (opening range, premarket high, yesterday's high/close, initial stop), BUY/SELL markers, the bot's own
log for that stock ("what the bot saw": the passing filter check, entry, partial, breakeven, exit) and ticker
details (sector, market cap, float, short interest, 52-week range, earnings date…). Yahoo keeps 5-minute bars for
about 60 days; older trades use hourly, then daily bars.

## Sleep and wake

Your PC can sleep. The task **HT_WakeUp** wakes it at 9:00 ET on weekdays, keeps it awake until 16:10 ET (no power
settings changed; it simply asks Windows not to sleep while it runs), and starts/logs in TWS if it isn't running.
Requirements: the PC must be **asleep, not shut down or signed out** (TWS needs your Windows desktop; a locked screen
is fine), plugged in is safest, and "Allow wake timers" must be on (setup enables it). Re-run the schedule (app button
"Re-install schedule") after updating so the new task is created.

## Automatic TWS paper login

Double-click **SETUP_AUTOLOGIN.bat** (after SETUP.bat). It downloads [IBC](https://github.com/IbcAlpha/IBC) (free,
open source) into `ibc/`, asks for your **paper** username and password (saved in `ibc/config.ini`, readable only by
your Windows user, never uploaded, untouched by app updates), and adds a weekday task `HT_TWSLogin` at 9:00 ET that
starts and logs in TWS if it isn't running, then messages you on Telegram. IBC also clicks "accept incoming
connection", sets the API to read/write, restarts TWS nightly at 11:45 PM, and logs in again for the weekly
re-authentication. The desktop shortcut uses it too.

Requirements: the **standalone ("Offline") TWS** installed in `C:\Jts\<version>` (IBC can't drive the self-updating
edition). Paper logins normally don't ask for IBKR Mobile approval; if yours does, approve it on your phone.

## Your live account (read-only analysis)

In the app, switch **🤖 Bot · paper / 💼 My live account**. The live view shows the same charts and gauges for your real
IBKR trades, kept completely separate from the bot's paper trades (`live_trades.csv`, never `trades.csv`).

- **Upload:** drop an IBKR Activity Statement (CSV) or Flex Query export (CSV/XML) on the page. Re-uploading only adds
  new trades. Several accounts (e.g. a Canadian and a US account) are kept apart, one account at a time, each in its
  own currency; positions in different accounts are never netted.
- **Automatic sync:** IBKR's Flex Web Service (read-only). Create an Activity Flex Query with the Trades section (XML),
  enable the Flex Web Service, and paste the token and query ID into the app (stored in `.env` as `FLEX_TOKEN` and
  `FLEX_QUERY_ID`). The app syncs at start-up and every 6 hours while open.
- Trades are counted flat-to-flat (long or short), using IBKR's own realized P&L (net of commissions) when the file
  has it. Positions opened before your file's date range are counted from IBKR's realized P&L only.

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
| `app.py` + `app_ui.html` + `icon.ico` | The desktop app: live bot + account view, pause/resume and run buttons |
| `launch.py` / `make_desktop_shortcut.py` | Desktop shortcut: opens TWS for login, then the app |
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
