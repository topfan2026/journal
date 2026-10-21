import { motion } from 'framer-motion';
import { ArrowRight, BarChart3, Cable, CandlestickChart, FlaskConical, Layers, LayoutGrid, NotebookPen, PencilRuler, Radar, Target, Wand2 } from 'lucide-react';
import { PriceChart } from './PriceChart';

const FEATURES = [
  { icon: CandlestickChart, title: 'Fast, fluid charts', body: 'Candles or lines, SMA / Bollinger overlays, RSI and MACD panes. Pan and zoom a year of data without a stutter.' },
  { icon: PencilRuler, title: 'Drawing tools', body: 'Trendlines, parallel price channels, horizontal levels and a measure tool that shows the move in $, % and bars.' },
  { icon: Layers, title: 'Option P&L zones', body: 'See exactly where a strategy wins or loses at expiration: shaded profit and loss bands with dashed breakevens, right on the price chart.' },
  { icon: Target, title: 'Trade from the chart', body: 'Right-click any price to place a limit or stop, then drag the order line to move it. Working orders update instantly.' },
  { icon: Radar, title: 'EasyScan screening', body: 'Sortable, live-updating scan results across S&P 500 and NASDAQ leaders, with presets for EPS growth, market cap, RSI and MACD.' },
  { icon: Wand2, title: 'Condition Wizard', body: 'Build custom conditions step by step — including Flex rules like "price above SMA 50 on 8 of the last 10 bars".' },
  { icon: BarChart3, title: 'Multi-leg options', body: 'One-click verticals, iron condors, straddles and strangles from a streaming chain, with max profit, max loss and breakevens.' },
  { icon: FlaskConical, title: 'Paper trading', body: 'Practise with a $100k simulated account. Brackets with profit target, stop and trailing stop are linked One-Cancels-All.' },
  { icon: NotebookPen, title: 'Journal & sticky notes', body: 'Keep a running journal per ticker and pin it to the chart. Everything saves automatically.' },
  { icon: LayoutGrid, title: 'Your workspace', body: 'Resizable panels and preset layouts — trader, quad charts, scan focus — remembered between sessions.' },
  { icon: Cable, title: 'Interactive Brokers data', body: 'Connect your IBKR account through the Client Portal Gateway for live quotes, history, balances and positions (read-only).' },
];

export function Landing({ onLaunch }: { onLaunch: () => void }) {
  return (
    <div className="min-h-screen overflow-y-auto bg-ink-950">
      <nav className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-4 sm:px-6">
        <span className="flex h-7 w-7 items-center justify-center rounded bg-accent"><BarChart3 size={15} /></span>
        <span className="font-semibold tracking-tight">ChartDesk</span>
        <button onClick={onLaunch} className="ml-auto rounded bg-accent px-3 py-1.5 text-sm font-medium hover:bg-blue-500">Launch platform</button>
      </nav>

      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pb-16 pt-8 sm:px-6 lg:grid-cols-[1fr_1.2fr]">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-ink-700 px-3 py-1 text-xs text-ink-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-up" /> Live simulated market · IBKR ready
          </div>
          <h1 className="text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
            Chart, scan and trade <span className="text-accent">in one place.</span>
          </h1>
          <p className="mt-4 max-w-lg text-ink-400">
            A dense, fast trading workspace: charts with drawing tools, EasyScan-style screening, a multi-leg option builder with P&amp;L zones on the chart, and a paper account with bracket orders.
          </p>
          <div className="mt-6 flex gap-3">
            <button onClick={onLaunch} className="flex items-center gap-2 rounded bg-accent px-5 py-2.5 font-medium hover:bg-blue-500">Open the platform <ArrowRight size={16} /></button>
            <a href="#features" className="rounded border border-ink-700 px-5 py-2.5 font-medium text-ink-300 hover:border-ink-500">See features</a>
          </div>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.6, delay: 0.1 }}
          className="h-[340px] overflow-hidden rounded-lg border border-ink-700 shadow-[0_30px_80px_-20px_rgba(59,130,246,0.35)]"
        >
          <PriceChart symbol="SPY" compact />
        </motion.div>
      </section>

      <section id="features" className="border-t border-ink-800 bg-ink-900/40">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 className="text-2xl font-semibold tracking-tight">Everything on one screen</h2>
          <p className="mt-2 text-ink-400">Every feature below is working in the app — click through and try it.</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <motion.button
                key={f.title}
                onClick={onLaunch}
                initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: (i % 3) * 0.06 }}
                className="group rounded-lg border border-ink-800 bg-ink-900 p-5 text-left transition-colors hover:border-accent/60"
              >
                <f.icon size={20} className="text-accent" />
                <div className="mt-3 font-semibold">{f.title}</div>
                <p className="mt-1 text-sm leading-relaxed text-ink-400">{f.body}</p>
              </motion.button>
            ))}
          </div>
        </div>
      </section>
      <footer className="border-t border-ink-800 px-4 py-6 text-center text-xs text-ink-500">
        For education and practice. Simulated data is not real market data. Not investment advice.
      </footer>
    </div>
  );
}
