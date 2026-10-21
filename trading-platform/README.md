# ChartDesk — trading platform workspace

A single-page trading workspace inspired by the TC2000 feature set: fast charts with drawing
tools, an EasyScan-style screener with a step-by-step Condition Wizard, a multi-leg option
strategy builder that paints **P&L zones** on the price chart, and a paper-trading account with
bracket (OCA) orders you can drag on the chart. It runs on realistic simulated data out of the box
and can stream **live data from your Interactive Brokers account**.

Stack: React 18 · TypeScript · Vite · Tailwind CSS · Zustand · Lightweight Charts · Framer Motion · Lucide.

## Quick start

```bash
cd trading-platform
npm install
npm run dev          # web app on http://localhost:5173 + IBKR bridge on :8787
```

Open http://localhost:5173 and click **Open the platform**. No account or API key is needed for
simulated data.

Other scripts: `npm test` (unit tests), `npm run typecheck`, `npm run build` (production bundle in `dist/`).

## What's in it

| Area | Where | Notes |
|---|---|---|
| Overview page | `/` | Feature tour with a live mini chart. |
| Workspace & layouts | Sidebar → Layouts | Trader, Quad Charts (4 independent charts), Scan Focus. Drag dividers to resize. Saved in the browser. |
| Watchlists | Sidebar → Watchlists | Mega Caps, S&P 500 leaders, NASDAQ 100, ETFs, plus an editable *My List*. |
| Indicators | Sidebar → Indicators | SMA 20/50/200, Bollinger Bands, volume, RSI and MACD panes; candles or line. |
| Drawing tools | Toolbar left of the chart | Trendline (2 clicks), price channel (3 clicks), horizontal line, measure ($, %, bars), eraser. |
| Trade from the chart | Right-click the chart | Places a buy/sell limit or stop at that price. **Drag any order line** to move it. |
| Bracket orders / OCA | Right panel → Trade | Entry + profit target + stop + trailing stop; exits activate when the entry fills and cancel each other. |
| Paper account | Bottom → Orders & Positions | $100k simulated account: equity, realized/unrealized P&L, working orders, fills. |
| Option builder | Right panel → Options | Presets (long call/put, bull call, bear put, iron condor, straddle, strangle), clickable streaming chain, payoff graph, max profit/loss, breakevens. |
| Option P&L zones | Price chart | Green/red bands between the last bar and expiration, dashed breakeven lines. Toggle with *P&L zones on chart*. |
| EasyScan | Bottom → EasyScan | Live, sortable table; preset scans (EPS growth, market cap, RSI cross, MACD breakout, uptrend, volume surge). |
| Condition Wizard | EasyScan → Condition Wizard | Indicator → comparison → value/indicator → **Flex** (true on N of the last M bars) → review. Save scans to Sidebar → Conditions. |
| Journal & sticky notes | Right panel → Journal | Per-ticker notes that autosave; pin one to the chart as a draggable sticky note. |

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
4. Run `npm run dev` (it starts the bridge too) and open the app.
5. Click **Simulated data** in the top bar — it switches to **IBKR live data** once the gateway
   reports you're authenticated. Click **Live** to see your real account balances and positions.

Notes:
- **Read-only by design.** Live mode shows your IBKR balances and positions; order entry stays on
  the paper account. Nothing in this app sends orders to IBKR.
- Live quotes need market-data subscriptions on your IBKR account; without them IBKR returns
  delayed data or nothing. Symbols IBKR can't serve fall back to simulated history.
- The gateway session times out after inactivity; the bridge pings `/tickle` every minute while
  it's running. If data stops, log in again at https://localhost:5000.
- Settings (environment variables for `npm run server`):
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
tests/                    vitest: options math, paper engine, scanner, IBKR parsing
```

For education and practice only. Simulated data is not real market data, and nothing here is
investment advice.
