# ChartDesk — trading platform workspace

A single-page trading workspace inspired by the TC2000 feature set: fast charts with drawing
tools, an EasyScan-style screener with a step-by-step Condition Wizard, a multi-leg option
strategy builder that paints **P&L zones** on the price chart, and a paper-trading account with
bracket (OCA) orders you can drag on the chart. It runs on realistic simulated data out of the box
and can stream **live data from your Interactive Brokers account**.

Stack: React 18 · TypeScript · Vite · Tailwind CSS · Zustand · Lightweight Charts · Framer Motion · Lucide.

## Desktop app (Windows / Mac / Linux)

ChartDesk is a desktop application (Electron). The IBKR bridge runs inside the app, so there is
nothing else to start except IBKR's own gateway when you want live data.

**Download an installer** from the latest release: https://github.com/topfan2026/journal/releases/latest
— `ChartDesk-Setup-<version>.exe` (Windows), `.dmg` (Mac) or `.AppImage` (Linux).

**Updates are automatic.** Every push to the app builds a new numbered release. ChartDesk checks
for one when it starts and every 4 hours (or **Help → Check for Updates…**), downloads it in the
background and asks you to restart. On Mac, unsigned apps can't replace themselves, so *Check for
Updates* opens the download page instead.

The installers are not code-signed, so the first launch shows a warning:
- **Windows:** "Windows protected your PC" → *More info* → *Run anyway*.
- **Mac:** right-click the app → *Open* → *Open* (or System Settings → Privacy & Security → *Open Anyway*).
  Use the `arm64` file for Apple Silicon (M1–M4) Macs and `x64` for Intel Macs.

**Build it yourself** (needs Node.js 20+):

```bash
cd trading-platform
npm install
npm run desktop      # build and open the desktop app
npm run dist         # build an installer for this OS into release/
```

## Developing in a browser

```bash
npm run dev          # web UI on http://localhost:5173 + IBKR bridge on :8787
```

Other scripts: `npm test` (unit tests), `npm run typecheck`, `npm run build` (production bundle in `dist/`).

## What's in it

The workspace is organised into **pages** (tabs along the bottom), each a layout of linked windows
that all follow the current symbol:

| Page | Windows |
|---|---|
| **Basic** | Chart · watchlist · option chain · My Favorites · News & Notes · Positions · Orders/Trades |
| **Trading** | Chart · order ticket with bracket exits / option strategy builder · Positions · Orders/Trades |
| **EasyScan** | Chart · watchlist · scanner with presets and the Condition Wizard |
| **Strategy Tester** | Strategy builder · backtest chart with trade markers and equity curve · stats, trades, walk-forward, watchlist test, live forward test |
| **1-Chart** | One full-size chart |
| **4-Timeframe** | The same symbol on 15m, 1h, daily and weekly side by side |
| **Options** | Chart with P&L zones · strategy builder · option chain |
| **Fundamentals** | Chart · company snapshot and performance · News & Notes |

Drag any divider to resize; sizes are remembered. A **ticker header** above every page shows the
selected stock's last price, change, bid × ask, open/high/low, previous close, volume vs. average,
Vol Buzz, day and 52-week ranges, market cap and EPS growth, plus flag and favorite toggles.

**Strategy Tester:**
- *Builder* — entry rules (all must be true) and exit rules (any), using the same indicators as
  EasyScan plus EMA 9/21, prior 20-bar high/low, Stochastic %K and ATR, each with Flex
  ("N of the last M bars"); stop %, target %, trailing stop %, max bars held; long or short;
  position size (% of equity or shares), commission and slippage. Starts from templates
  (SMA crossover, RSI mean reversion, 20-bar breakout, MACD trend, EMA short).
- *Back test* — signals at bar close, fills at the next open (no look-ahead); stops/targets checked
  inside each bar (stop first if both are touched, gaps fill at the open). Stats: net profit, buy &
  hold, trades, win rate, profit factor, average trade/win/loss, max drawdown, Sharpe, exposure.
  An in-sample / out-of-sample split shows whether results hold on data the rules weren't tuned on.
- *Walk-forward* — optimizes up to two parameters on each in-sample window and trades the next unseen
  window with the winners, chaining the out-of-sample results into one equity curve.
- *Watchlist test* — runs the strategy on every symbol in a list and ranks the results.
- *Forward test* — runs the strategy live on incoming prices (simulated or IBKR) and places bracket
  orders in the paper account, with a log and P&L per symbol.

**Charts:** 1m / 5m / 15m / 1h / daily / weekly; candles, OHLC bars or line; log scale; indicator
menu (MA 20/50/200, EMA 9/21, Bollinger Bands, Volume + MA 50, RSI, MACD, Stochastics); drawing
tools (trendline, channel, horizontal line, measure); Buy / Sell / Opt buttons; right-click any
price for limit/stop orders, a price alert, a horizontal line or a sticky note; drag order lines to
move them; option strategies draw profit/loss zones and breakevens through expiration.

**Watchlists:** High Cap (99 stocks), Mega Caps, NASDAQ 100, sectors, ETFs, Flagged and My Favorites,
with % change, **Vol Buzz** (volume vs. its 50-day average), colour flags (click the flag column) and
sorting.

**Keyboard:** type letters anywhere to jump to a symbol · ↑ / ↓ or Space to step through the
watchlist · **Shift+V** adds the current symbol to My Favorites · Esc drops the drawing tool.

**Trading (paper):** $100k practice account; account strip shows today's P&L, long value, cash,
account value and buying power. Bracket orders (target, stop, trailing stop) are One-Cancels-All.
Positions and Orders/Trades windows use the familiar columns (Day P&L, Mkt Val, Unreal P&L, Dist,
Est P&L, OCA, …).

**Alerts:** toolbar → Alerts, or right-click a chart price. Triggered alerts pop a toast and a
desktop notification.

## Connect Interactive Brokers (live data)

The app reads live data through IBKR's **Client Portal Web API**. Your IBKR login happens in IBKR's
own gateway on your computer — the app never sees your password.

1. Install Java 8+ and download the **Client Portal Gateway** from IBKR
   (search "IBKR Client Portal API gateway download"). Unzip it.
2. Start it from the unzipped folder:
   - macOS/Linux: `bin/run.sh root/conf.yaml`
   - Windows: `bin\run.bat root\conf.yaml`
3. Open https://localhost:5000 in your browser, accept the self-signed certificate warning, and log
   in with your IBKR username/password (and 2FA). You should see "Client login succeeds".
4. Open ChartDesk (or run `npm run dev` when developing in a browser).
5. Click **Simulated data** in the top bar — it switches to **IBKR live data** once the gateway
   reports you're authenticated. Click **Live** to see your real account balances and positions.

Notes:
- **Read-only by design.** Live mode shows your IBKR balances and positions; order entry stays on
  the paper account. Nothing in this app sends orders to IBKR.
- Live quotes need market-data subscriptions on your IBKR account; without them IBKR returns
  delayed data or nothing. Symbols IBKR can't serve fall back to simulated history.
- The gateway session times out after inactivity; the bridge pings `/tickle` every minute while
  it's running. If data stops, log in again at https://localhost:5000.
- The **IBKR** menu in the desktop app has shortcuts to the gateway login page and download.
- Settings (environment variables):
  - `IBKR_GATEWAY_URL` — default `https://localhost:5000`
  - `IBKR_ALLOW_SELF_SIGNED` — defaults to `true` only for a localhost gateway
  - `PORT` — bridge port, default `8787` (the bridge only listens on 127.0.0.1)

## Project layout

```
src/
  App.tsx                 routes: overview page (#/) and platform (#/app)
  components/             PriceChart, Sidebar, Workspace, TradeTicket, OptionsPanel,
                          ScannerPanel (+ Condition Wizard), OrdersPanel, JournalPanel, …
  store/market.ts         bars per symbol, data source (mock / IBKR), live ticks
  store/workspace.ts      persisted UI + paper account state (Zustand)
  lib/indicators.ts       SMA, EMA, RSI, MACD, Bollinger
  lib/scanner.ts          scan metrics, conditions, Flex evaluation, presets
  lib/options.ts          Black-Scholes, simulated chain, payoff analysis, strategy presets
  lib/paper.ts            paper-trading engine: brackets, trailing stops, OCA
  lib/useMarketFeed.ts    1s simulated ticks or 2s IBKR snapshots → paper engine
  data/                   symbol universe, watchlists, seeded OHLC generator
server/
  index.js, ibkr.js       local read-only bridge to the IBKR Client Portal Gateway
electron/
  main.js                 desktop shell: runs the bridge + serves the UI on 127.0.0.1, opens the window
tests/                    vitest: options math, paper engine, scanner, IBKR parsing
```

For education and practice only. Simulated data is not real market data, and nothing here is
investment advice.
