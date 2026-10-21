import { useEffect, useState } from 'react';
import { RotateCcw, X } from 'lucide-react';
import { useMarket } from '../store/market';
import { useWorkspace } from '../store/workspace';
import { equity, STARTING_CASH } from '../lib/paper';
import { ibkr, type IbkrPosition, type IbkrSummary } from '../lib/ibkr';
import { usd, tone } from '../lib/format';
import { Stat } from './ui';

export function OrdersPanel() {
  const mode = useWorkspace((s) => s.mode);
  return mode === 'live' ? <LiveAccount /> : <PaperAccount />;
}

function PaperAccount() {
  const { paper, cancelOrder, resetPaper, setSymbol } = useWorkspace();
  const bars = useMarket((s) => s.bars);
  const prices = Object.fromEntries(Object.entries(bars).map(([s, b]) => [s, b[b.length - 1]?.close ?? 0]));
  const eq = equity(paper, prices);
  const unreal = Object.values(paper.positions).reduce((a, p) => a + (prices[p.symbol] - p.avgPrice) * p.qty, 0);
  const working = paper.orders.filter((o) => o.status === 'WORKING');
  const history = paper.orders.filter((o) => o.status !== 'WORKING').slice(-30).reverse();
  const parentLabel = (pid?: string) => (pid ? (paper.orders.find((o) => o.id === pid)?.status === 'FILLED' ? 'active' : 'pending entry') : '');

  return (
    <div className="grid h-full grid-cols-1 gap-2 overflow-auto p-2 text-xs lg:grid-cols-[220px_1fr_1fr]">
      <div className="space-y-1.5">
        <Stat label="Equity" value={usd(eq)} />
        <div className="grid grid-cols-2 gap-1.5">
          <Stat label="Cash" value={usd(paper.cash, 0)} />
          <Stat label="Total P&L" value={usd(eq - STARTING_CASH, 0)} className={tone(eq - STARTING_CASH)} />
          <Stat label="Unrealized" value={usd(unreal, 0)} className={tone(unreal)} />
          <Stat label="Realized" value={usd(paper.realized, 0)} className={tone(paper.realized)} />
        </div>
        <button onClick={() => confirm('Reset the paper account to $100,000?') && resetPaper()} className="flex items-center gap-1 text-2xs text-ink-500 hover:text-ink-100"><RotateCcw size={11} /> Reset paper account</button>
      </div>

      <Section title={`Positions (${Object.keys(paper.positions).length})`}>
        <table className="w-full font-mono text-2xs">
          <thead className="text-ink-500"><tr><th className="text-left">Sym</th><th className="text-right">Qty</th><th className="text-right">Avg</th><th className="text-right">Last</th><th className="text-right">P&amp;L</th></tr></thead>
          <tbody>
            {Object.values(paper.positions).map((p) => {
              const pl = (prices[p.symbol] - p.avgPrice) * p.qty;
              return (
                <tr key={p.symbol} className="cursor-pointer hover:bg-ink-800" onClick={() => setSymbol(p.symbol)}>
                  <td className="py-0.5 font-sans font-semibold">{p.symbol}</td><td className={`text-right ${tone(p.qty)}`}>{p.qty}</td>
                  <td className="text-right">{p.avgPrice.toFixed(2)}</td><td className="text-right">{prices[p.symbol]?.toFixed(2)}</td>
                  <td className={`text-right ${tone(pl)}`}>{usd(pl, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="mt-3 mb-1 text-2xs uppercase tracking-wide text-ink-500">Fills &amp; cancels</div>
        {history.map((o) => (
          <div key={o.id} className="flex gap-2 font-mono text-2xs text-ink-400">
            <span className={o.status === 'FILLED' ? 'text-ink-100' : 'line-through'}>{o.side} {o.qty} {o.symbol}</span>
            <span>{o.label ?? o.type}</span>
            <span className="ml-auto">{o.status === 'FILLED' ? `@ ${o.fillPrice?.toFixed(2)}` : 'cancelled'}</span>
          </div>
        ))}
      </Section>

      <Section title={`Working orders (${working.length})`}>
        {working.map((o) => (
          <div key={o.id} className={`flex items-center gap-2 border-t border-ink-800/60 py-1 font-mono text-2xs ${o.parentId ? 'pl-3' : ''}`}>
            <span className={o.side === 'BUY' ? 'text-up' : 'text-down'}>{o.side}</span>
            <span className="font-sans font-semibold">{o.symbol}</span>
            <span>{o.qty}</span>
            <span className="text-ink-400">{o.type}{o.type === 'TRAIL' ? ` $${o.trailAmount}` : ` ${o.price?.toFixed(2)}`}</span>
            {o.label && <span className="rounded bg-ink-800 px-1 font-sans text-ink-300">{o.label}</span>}
            {o.ocaGroup && <span className="rounded bg-purple-500/15 px-1 font-sans text-purple-300" title="One-Cancels-All group">OCA</span>}
            {o.parentId && <span className="font-sans text-ink-500">{parentLabel(o.parentId)}</span>}
            <button className="ml-auto text-ink-500 hover:text-down" onClick={() => cancelOrder(o.id)} aria-label="Cancel order"><X size={12} /></button>
          </div>
        ))}
        {!working.length && <div className="py-4 text-center text-ink-500">No working orders</div>}
      </Section>
    </div>
  );
}

function LiveAccount() {
  const [summary, setSummary] = useState<IbkrSummary | null>(null);
  const [positions, setPositions] = useState<IbkrPosition[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    const load = () => Promise.all([ibkr.summary(), ibkr.positions()])
      .then(([s, p]) => { if (alive) { setSummary(s); setPositions(p); setError(''); } })
      .catch((e) => alive && setError(String(e.message ?? e)));
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (error) return (
    <div className="p-4 text-xs text-ink-400">
      <div className="mb-1 font-semibold text-down">Can't reach your IBKR account</div>
      <div className="font-mono text-2xs">{error}</div>
      <p className="mt-2">Start the IBKR Client Portal Gateway, log in at https://localhost:5000, then make sure the bridge (<code>npm run server</code>) is running. See README → "Connect Interactive Brokers".</p>
    </div>
  );
  return (
    <div className="grid h-full grid-cols-1 gap-2 overflow-auto p-2 text-xs lg:grid-cols-[220px_1fr]">
      <div className="space-y-1.5">
        <Stat label={`IBKR ${summary?.accountId ?? ''}`} value={summary?.netLiquidation != null ? usd(summary.netLiquidation) : '…'} />
        <div className="grid grid-cols-2 gap-1.5">
          <Stat label="Cash" value={summary?.cash != null ? usd(summary.cash, 0) : '—'} />
          <Stat label="Buying power" value={summary?.buyingPower != null ? usd(summary.buyingPower, 0) : '—'} />
        </div>
        <p className="text-2xs text-ink-500">Read-only. Refreshes every 10s.</p>
      </div>
      <Section title={`IBKR positions (${positions.length})`}>
        <table className="w-full font-mono text-2xs">
          <thead className="text-ink-500"><tr><th className="text-left">Sym</th><th className="text-left">Type</th><th className="text-right">Qty</th><th className="text-right">Avg</th><th className="text-right">Mkt</th><th className="text-right">Unreal. P&amp;L</th></tr></thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.symbol + p.assetClass}>
                <td className="py-0.5 font-sans font-semibold">{p.symbol}</td><td className="text-ink-400">{p.assetClass}</td>
                <td className={`text-right ${tone(p.qty)}`}>{p.qty}</td><td className="text-right">{p.avgPrice.toFixed(2)}</td>
                <td className="text-right">{p.mktPrice.toFixed(2)}</td><td className={`text-right ${tone(p.unrealizedPnl)}`}>{usd(p.unrealizedPnl, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded border border-ink-800 bg-ink-950/50 p-2">
      <div className="mb-1 text-2xs font-semibold uppercase tracking-wide text-ink-400">{title}</div>
      {children}
    </div>
  );
}
